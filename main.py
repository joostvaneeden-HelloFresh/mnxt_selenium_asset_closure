"""
MobileNXT Asset Damage Closer
Logt in, sorteert assets op active damages (hoog→laag), en sluit
alle damages met status New/Checked af op Resolved.

Gebruik:
    pip install -r requirements.txt
    cp .env.example .env  # vul credentials in
    python main.py
"""

import os
import time
import logging
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

BASE_URL = os.getenv("MNXT_BASE_URL", "https://hellofresh-qa.mobilenext.eu")
LOGIN_URL = f"{BASE_URL}/login"

WAIT = 15
SHORT = 2

# Statussen die we moeten sluiten
TE_SLUITEN_STATUSSEN = {"new", "checked"}


def make_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--window-size=1440,900")
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    except Exception:
        return webdriver.Chrome(options=opts)


def wacht(driver, locator, timeout=WAIT):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located(locator)
    )


def klikbaar(driver, locator, timeout=WAIT):
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable(locator)
    )


def js_click(driver, el):
    driver.execute_script("arguments[0].click();", el)


class MNXTSession:
    def __init__(self, driver: webdriver.Chrome):
        self.d = driver

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def login(self, username: str, password: str):
        log.info("Login: %s", LOGIN_URL)
        self.d.get(LOGIN_URL)

        def vul_in(sel, waarde):
            el = wacht(self.d, sel)
            el.click()
            self.d.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                el, waarde
            )
            el.send_keys(" ")
            el.send_keys(Keys.BACK_SPACE)

        vul_in((By.CSS_SELECTOR, "input[autocomplete='email']"), username)
        vul_in((By.CSS_SELECTOR, "input[type='password']"), password)
        time.sleep(1)
        btn = klikbaar(self.d, (By.CSS_SELECTOR, "button[type='submit']"))
        js_click(self.d, btn)
        WebDriverWait(self.d, WAIT).until(EC.url_changes(LOGIN_URL))
        time.sleep(3)
        log.info("Ingelogd")

    # ------------------------------------------------------------------
    # Asset Monitor — sorteer op Active Damages hoog→laag
    # ------------------------------------------------------------------

    def sorteer_op_active_damages(self):
        log.info("Sorteer op Active Damages")
        header = klikbaar(self.d, (
            By.XPATH,
            "//th[.//text()[contains(.,'Active') and contains(.,'Damages')] "
            "or .//span[contains(text(),'Active Damages')]]"
        ))
        js_click(self.d, header)
        time.sleep(SHORT)

    # ------------------------------------------------------------------
    # Loop door alle assets
    # ------------------------------------------------------------------

    def verwerk_alle_assets(self):
        verwerkt = 0
        while True:
            rijen = self._haal_asset_rijen_met_damages()
            if not rijen:
                log.info("Geen assets meer met active damages")
                break
            log.info("%d asset(s) met active damages op deze pagina", len(rijen))

            # Verwerk altijd de eerste rij opnieuw (na terugkeer refresht de lijst)
            for i in range(len(rijen)):
                rijen = self._haal_asset_rijen_met_damages()
                if not rijen:
                    break
                rij = rijen[0]
                referentie = self._lees_referentie(rij)
                log.info("─" * 50)
                log.info("Asset: %s", referentie)
                js_click(self.d, rij)
                time.sleep(SHORT)
                gesloten = self._verwerk_damages_van_asset(referentie)
                log.info("[%s] %d damage(s) gesloten", referentie, gesloten)
                self.d.back()
                time.sleep(SHORT)
                verwerkt += 1

            # Controleer of er een volgende pagina is
            if not self._volgende_pagina():
                break

        log.info("Klaar — %d assets verwerkt", verwerkt)

    def _haal_asset_rijen_met_damages(self) -> list:
        try:
            rijen = WebDriverWait(self.d, WAIT).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "table tbody tr")
                )
            )
        except TimeoutException:
            return []

        resultaat = []
        for rij in rijen:
            try:
                # Kolom "Active Damages" — zoek cel met getal > 0
                cellen = rij.find_elements(By.CSS_SELECTOR, "td")
                for cel in cellen:
                    tekst = cel.text.strip()
                    if tekst.isdigit() and int(tekst) > 0:
                        resultaat.append(rij)
                        break
            except StaleElementReferenceException:
                continue
        return resultaat

    def _lees_referentie(self, rij) -> str:
        try:
            return rij.find_element(By.CSS_SELECTOR, "td:first-child").text.strip()
        except Exception:
            return "onbekend"

    def _volgende_pagina(self) -> bool:
        try:
            volgende = self.d.find_element(
                By.XPATH,
                "//button[@aria-label='Next page' or contains(@class,'mat-paginator-navigation-next')]"
            )
            if volgende.is_enabled():
                js_click(self.d, volgende)
                time.sleep(SHORT)
                return True
        except NoSuchElementException:
            pass
        return False

    # ------------------------------------------------------------------
    # Asset detail: Damages tab
    # ------------------------------------------------------------------

    def _verwerk_damages_van_asset(self, referentie: str) -> int:
        # Klik op de Damages tab
        try:
            tab = klikbaar(self.d, (
                By.XPATH,
                "//div[contains(@class,'mat-tab-label') and contains(.,'Damages')]"
                " | //a[contains(@class,'mat-tab') and contains(.,'Damages')]"
                " | //*[@role='tab' and contains(.,'Damages')]"
            ))
            js_click(self.d, tab)
            time.sleep(SHORT)
        except TimeoutException:
            log.warning("[%s] Damages tab niet gevonden", referentie)
            return 0

        gesloten = 0
        # Blijf damage rijen ophalen en sluiten totdat er geen open meer zijn
        while True:
            damage_rijen = self._haal_open_damage_rijen()
            if not damage_rijen:
                break
            log.info("[%s] Open damage gevonden, sluiten...", referentie)
            if self._sluit_damage(damage_rijen[0], referentie):
                gesloten += 1
            else:
                break
        return gesloten

    def _haal_open_damage_rijen(self) -> list:
        """Geeft rijen terug waarvan de status New of Checked is."""
        try:
            rijen = WebDriverWait(self.d, SHORT).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "table tbody tr")
                )
            )
        except TimeoutException:
            return []

        open_rijen = []
        for rij in rijen:
            try:
                # Zoek statusbadge in de rij
                badges = rij.find_elements(
                    By.XPATH,
                    ".//span[contains(@class,'badge') or contains(@class,'chip') "
                    "or contains(@class,'status') or contains(@class,'mat-chip')]"
                )
                for badge in badges:
                    if badge.text.strip().lower() in TE_SLUITEN_STATUSSEN:
                        open_rijen.append(rij)
                        break
                # Fallback: zoek op kleur (rode badge = New)
                if not open_rijen or rij not in open_rijen:
                    rode_els = rij.find_elements(
                        By.XPATH,
                        ".//*[contains(@style,'background') or contains(@class,'warn') "
                        "or contains(@class,'danger') or contains(@class,'error')]"
                    )
                    for el in rode_els:
                        if el.text.strip().lower() in TE_SLUITEN_STATUSSEN:
                            open_rijen.append(rij)
                            break
            except StaleElementReferenceException:
                continue
        return open_rijen

    def _sluit_damage(self, rij, referentie: str) -> bool:
        # Klik op de rij om naar de damage detail pagina te gaan
        try:
            js_click(self.d, rij)
            time.sleep(SHORT)
        except Exception as e:
            log.error("[%s] Kan damage rij niet klikken: %s", referentie, e)
            return False

        # Klik Change Status
        try:
            btn = klikbaar(self.d, (
                By.XPATH,
                "//button[contains(.,'Change Status') or contains(.,'Change status')]"
            ))
            js_click(self.d, btn)
            time.sleep(SHORT)
        except TimeoutException:
            log.error("[%s] 'Change Status' knop niet gevonden", referentie)
            self.d.back()
            time.sleep(SHORT)
            return False

        # Selecteer "Resolved" in de dropdown
        try:
            dropdown = klikbaar(self.d, (By.CSS_SELECTOR, "mat-select, select"))
            js_click(self.d, dropdown)
            time.sleep(1)
            resolved_optie = klikbaar(self.d, (
                By.XPATH,
                "//mat-option[contains(.,'Resolved')] | //option[contains(.,'Resolved')]"
            ))
            js_click(self.d, resolved_optie)
            time.sleep(1)
        except TimeoutException:
            log.error("[%s] 'Resolved' optie niet gevonden", referentie)
            # Sluit modal en ga terug
            try:
                klikbaar(self.d, (By.XPATH, "//button[contains(.,'Cancel')]"))
            except Exception:
                pass
            self.d.back()
            time.sleep(SHORT)
            return False

        # Bevestig
        try:
            confirm = klikbaar(self.d, (
                By.XPATH,
                "//button[contains(.,'Confirm') or contains(.,'confirm')]"
            ))
            js_click(self.d, confirm)
            time.sleep(SHORT)
            log.info("[%s] Damage gesloten op Resolved", referentie)
        except TimeoutException:
            log.error("[%s] 'Confirm' knop niet gevonden", referentie)
            self.d.back()
            time.sleep(SHORT)
            return False

        # Ga terug naar de damages tab van het asset
        self.d.back()
        time.sleep(SHORT)
        return True


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    username = os.getenv("MNXT_USERNAME")
    password = os.getenv("MNXT_PASSWORD")

    if not username or not password:
        raise SystemExit("Vul MNXT_USERNAME en MNXT_PASSWORD in (.env bestand)")

    driver = make_driver()
    try:
        sessie = MNXTSession(driver)
        sessie.login(username, password)
        sessie.sorteer_op_active_damages()
        sessie.verwerk_alle_assets()
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
