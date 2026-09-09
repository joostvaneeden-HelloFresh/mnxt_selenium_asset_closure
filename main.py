"""
MobileNXT Asset Closure Simulator
Simuleert het sluiten van schades per kenteken in MobileNXT.

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
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    ElementClickInterceptedException,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuratie — pas selectors hieronder aan op basis van de echte MobileNXT UI
# ---------------------------------------------------------------------------

BASE_URL = os.getenv("MNXT_BASE_URL", "https://hellofresh-qa.mobilenext.eu")
LOGIN_URL = f"{BASE_URL}/login"

# Seleniumwaits (seconden)
WAIT_TIMEOUT = 15
SHORT_WAIT = 3

# Login pagina selectors
SEL_USERNAME_INPUT = (By.CSS_SELECTOR, "input[autocomplete='email']")
SEL_PASSWORD_INPUT = (By.CSS_SELECTOR, "input[type='password']")
SEL_LOGIN_BUTTON = (By.CSS_SELECTOR, "button[type='submit']")

# Navigatie naar assets / kentekens
SEL_ASSETS_MENU = (By.LINK_TEXT, "Assets")        # TODO: pas aan op menu-tekst
SEL_ASSET_ROWS = (By.CSS_SELECTOR, "table tbody tr")  # TODO: rijen in asset-overzicht
SEL_ASSET_KENTEKEN = (By.CSS_SELECTOR, "td:first-child")  # TODO: kolom met kenteken

# Schade-pagina selectors
SEL_SCHADES_TAB = (By.XPATH, "//a[contains(text(),'Schade') or contains(text(),'Damage')]")
SEL_SCHADE_ROWS = (By.CSS_SELECTOR, ".damage-list tr, table.schades tbody tr")  # TODO
SEL_SCHADE_OPEN_STATUS = (By.CSS_SELECTOR, "td.status")  # TODO: statuskolom
SEL_SCHADE_OPEN_BTN = (By.CSS_SELECTOR, "a.schade-detail, a.damage-detail")  # TODO: detail-link
SEL_SCHADE_SLUIT_BTN = (
    By.XPATH,
    "//button[contains(text(),'Sluit') or contains(text(),'Sluiten') "
    "or contains(text(),'Close') or contains(text(),'Afsluiten')]",
)
SEL_CONFIRM_BTN = (
    By.XPATH,
    "//button[contains(text(),'Bevestig') or contains(text(),'Confirm') "
    "or contains(text(),'OK') or contains(text(),'Ja')]",
)

# Status waarde die een open/actieve schade aangeeft
OPEN_STATUS_TEXTS = {"open", "actief", "active", "in behandeling"}

# ---------------------------------------------------------------------------


def make_driver(headless: bool = False) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1440,900")
    # Gebruik systeembrede chromedriver als webdriver-manager faalt
    try:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=opts)
    except Exception:
        return webdriver.Chrome(options=opts)


def wait_for(driver: webdriver.Chrome, selector: tuple, timeout: int = WAIT_TIMEOUT):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located(selector)
    )


def click(driver: webdriver.Chrome, selector: tuple, timeout: int = WAIT_TIMEOUT):
    el = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable(selector)
    )
    try:
        el.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", el)
    return el


class MobileNXTSession:
    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.wait = WebDriverWait(driver, WAIT_TIMEOUT)

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------

    def login(self, username: str, password: str):
        log.info("Navigeer naar loginpagina: %s", LOGIN_URL)
        self.driver.get(LOGIN_URL)
        wait_for(self.driver, SEL_USERNAME_INPUT).send_keys(username)
        self.driver.find_element(*SEL_PASSWORD_INPUT).send_keys(password)
        click(self.driver, SEL_LOGIN_BUTTON)
        # Wacht tot pagina geladen is (URL verandert na login)
        WebDriverWait(self.driver, WAIT_TIMEOUT).until(
            EC.url_changes(LOGIN_URL)
        )
        log.info("Ingelogd als %s", username)

    # ------------------------------------------------------------------
    # Asset/kenteken navigatie
    # ------------------------------------------------------------------

    def haal_kentekens_op(self) -> list[str]:
        """
        Haal alle kentekens op uit het asset-overzicht.
        Wordt alleen gebruikt als KENTEKENS env leeg is.
        """
        log.info("Navigeer naar assets overzicht")
        click(self.driver, SEL_ASSETS_MENU)
        rijen = self.wait.until(
            EC.presence_of_all_elements_located(SEL_ASSET_ROWS)
        )
        kentekens = []
        for rij in rijen:
            try:
                kenteken = rij.find_element(*SEL_ASSET_KENTEKEN).text.strip()
                if kenteken:
                    kentekens.append(kenteken)
            except NoSuchElementException:
                continue
        log.info("Gevonden kentekens: %s", kentekens)
        return kentekens

    def navigeer_naar_asset(self, kenteken: str):
        """Zoek kenteken in de lijst en klik erop."""
        log.info("Navigeer naar asset: %s", kenteken)
        rijen = self.wait.until(
            EC.presence_of_all_elements_located(SEL_ASSET_ROWS)
        )
        for rij in rijen:
            try:
                cel = rij.find_element(*SEL_ASSET_KENTEKEN)
                if kenteken.upper() in cel.text.upper():
                    cel.click()
                    time.sleep(SHORT_WAIT)
                    return
            except NoSuchElementException:
                continue
        raise RuntimeError(f"Kenteken niet gevonden in lijst: {kenteken}")

    # ------------------------------------------------------------------
    # Schade sluiten
    # ------------------------------------------------------------------

    def open_schades_tab(self):
        """Navigeer naar de schades-tab op de asset-detailpagina."""
        try:
            click(self.driver, SEL_SCHADES_TAB)
            time.sleep(SHORT_WAIT)
        except TimeoutException:
            log.warning("Schades-tab niet gevonden — mogelijk al op de juiste pagina")

    def sluit_alle_open_schades(self, kenteken: str) -> int:
        """Sluit alle open schades voor het huidige asset. Geeft aantal gesloten terug."""
        gesloten = 0
        while True:
            schades = self._haal_open_schades()
            if not schades:
                log.info("[%s] Geen open schades meer", kenteken)
                break
            log.info("[%s] %d open schade(s) gevonden", kenteken, len(schades))
            # Klik op de eerste open schade
            try:
                schades[0].click()
                time.sleep(SHORT_WAIT)
            except Exception as e:
                log.error("[%s] Kan schade niet openen: %s", kenteken, e)
                break
            # Sluit de schade
            if self._sluit_schade(kenteken):
                gesloten += 1
            else:
                log.warning("[%s] Kon schade niet sluiten, stop loop", kenteken)
                break
        return gesloten

    def _haal_open_schades(self) -> list:
        """Geeft lijst van klikbare elementen voor open schades terug."""
        try:
            rijen = WebDriverWait(self.driver, SHORT_WAIT).until(
                EC.presence_of_all_elements_located(SEL_SCHADE_ROWS)
            )
        except TimeoutException:
            return []

        open_schades = []
        for rij in rijen:
            try:
                status_el = rij.find_element(*SEL_SCHADE_OPEN_STATUS)
                if status_el.text.strip().lower() in OPEN_STATUS_TEXTS:
                    try:
                        link = rij.find_element(*SEL_SCHADE_OPEN_BTN)
                        open_schades.append(link)
                    except NoSuchElementException:
                        open_schades.append(rij)
            except NoSuchElementException:
                continue
        return open_schades

    def _sluit_schade(self, kenteken: str) -> bool:
        """Klik op de sluit-knop en bevestig. Geeft True terug bij succes."""
        try:
            click(self.driver, SEL_SCHADE_SLUIT_BTN)
            log.info("[%s] Sluit-knop geklikt", kenteken)
        except TimeoutException:
            log.error("[%s] Sluit-knop niet gevonden", kenteken)
            return False

        # Bevestigingsdialoog (optioneel — sommige flows hebben dit niet)
        try:
            click(self.driver, SEL_CONFIRM_BTN, timeout=5)
            log.info("[%s] Bevestigd", kenteken)
        except TimeoutException:
            log.debug("[%s] Geen bevestigingsdialoog nodig", kenteken)

        time.sleep(SHORT_WAIT)
        return True

    # ------------------------------------------------------------------
    # Hoofd-loop
    # ------------------------------------------------------------------

    def verwerk_kentekens(self, kentekens: list[str]):
        for i, kenteken in enumerate(kentekens, start=1):
            log.info("─" * 50)
            log.info("Verwerk %d/%d: %s", i, len(kentekens), kenteken)
            try:
                self.navigeer_naar_asset(kenteken)
                self.open_schades_tab()
                gesloten = self.sluit_alle_open_schades(kenteken)
                log.info("[%s] Klaar — %d schade(s) gesloten", kenteken, gesloten)
            except Exception as e:
                log.error("[%s] Fout bij verwerking: %s", kenteken, e)
                # Ga terug naar assets-overzicht en ga door
                try:
                    click(self.driver, SEL_ASSETS_MENU, timeout=5)
                    time.sleep(SHORT_WAIT)
                except Exception:
                    self.driver.get(BASE_URL)
                    time.sleep(SHORT_WAIT)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    username = os.getenv("MNXT_USERNAME")
    password = os.getenv("MNXT_PASSWORD")
    kentekens_env = os.getenv("KENTEKENS", "")

    if not username or not password:
        raise SystemExit(
            "Vul MNXT_USERNAME en MNXT_PASSWORD in (in .env of omgevingsvariabelen)"
        )

    driver = make_driver(headless=False)
    try:
        sessie = MobileNXTSession(driver)
        sessie.login(username, password)

        if kentekens_env.strip():
            kentekens = [k.strip() for k in kentekens_env.split(",") if k.strip()]
            log.info("Kentekens uit .env: %s", kentekens)
        else:
            kentekens = sessie.haal_kentekens_op()

        if not kentekens:
            log.warning("Geen kentekens gevonden om te verwerken")
            return

        sessie.verwerk_kentekens(kentekens)
        log.info("=" * 50)
        log.info("Klaar. Alle kentekens verwerkt.")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
