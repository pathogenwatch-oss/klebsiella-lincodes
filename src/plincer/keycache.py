import dataclasses
import json
import logging
import re
from pathlib import Path
from typing import TypedDict, cast
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag
from rauth import OAuth1Service, OAuth1Session

logger = logging.getLogger(__name__)


class HostConfig(TypedDict):
    REST_URL: str
    WEB_URL: str
    LOGIN_DB: dict[str, str]


@dataclasses.dataclass
class KeyCache:
    secrets_file: Path
    host_config_file: Path
    cache_file: Path

    __secrets: dict[str, dict[str, dict[str, str]]] = dataclasses.field(
        init=False, repr=False
    )
    __host_config: dict[str, HostConfig] = dataclasses.field(init=False, repr=False)
    __cache: dict[str, dict[str, dict[str, str]]] = dataclasses.field(
        init=False, repr=False
    )
    __logged_in_session: dict[str, requests.Session] = dataclasses.field(
        default_factory=dict, repr=False
    )

    def __post_init__(self) -> None:
        self.__secrets: dict[str, dict[str, dict[str, str]]] = self.load_secrets()
        self.__host_config = self.load_config(self.host_config_file)
        self.__cache: dict[str, dict[str, dict[str, str]]] = self.load_cache()
        self.__initialize_cache_from_secrets()

    @staticmethod
    def __is_bigsdb(host: str) -> bool:
        return host in {"pubmlst", "pasteur"}

    def __initialize_cache_from_secrets(self) -> None:
        for host, host_data in self.__secrets.items():
            if host not in self.__cache:
                self.__cache[host] = {}
            for key_type, key_data in host_data.items():
                if key_type not in ["user", "consumer"]:
                    self.__cache[host][key_type] = key_data
        self.save_cache()

    def load_secrets(self) -> dict[str, dict[str, dict[str, str]]]:
        if not self.secrets_file.exists():
            raise FileNotFoundError(f"Secrets file not found: {self.secrets_file}")
        with open(self.secrets_file, "r") as f:
            return json.load(f)

    def load_cache(self) -> dict[str, dict[str, dict[str, str]]]:
        if not self.cache_file.exists():
            return {}
        with open(self.cache_file, "r") as f:
            return json.load(f)

    def save_cache(self) -> None:
        with open(self.cache_file, "w") as f:
            json.dump(self.__cache, f, indent=2)

    @staticmethod
    def __cache_key(key_type: str, database: str | None = None) -> str:
        return key_type if database is None else f"{database}:{key_type}"

    def get_key(
        self, key_type: str, host: str, database: str | None = None
    ) -> tuple[str, str] | None:
        if not self.__is_bigsdb(host):
            return None
        if key_type in ["user", "consumer"]:
            if host not in self.__secrets or key_type not in self.__secrets[host]:
                raise KeyError(
                    f"{key_type.capitalize()} for {host} not found in secrets file"
                )
            return self.__secrets[host][key_type]["TOKEN"], self.__secrets[host][
                key_type
            ]["TOKEN SECRET"]
        else:
            cache_key = self.__cache_key(key_type, database)
            if host in self.__cache and cache_key in self.__cache[host]:
                return self.__cache[host][cache_key]["TOKEN"], self.__cache[host][
                    cache_key
                ]["TOKEN SECRET"]
            return None

    def set_key(
        self,
        key_type: str,
        host: str,
        token: str,
        token_secret: str,
        database: str | None = None,
    ) -> None:
        if key_type in ["user", "consumer"]:
            logger.warning(f"Attempt to set {key_type} token for {host} ignored.")
            return
        if host not in self.__cache:
            self.__cache[host] = {}
        cache_key = self.__cache_key(key_type, database)
        self.__cache[host][cache_key] = {"TOKEN": token, "TOKEN SECRET": token_secret}
        self.save_cache()

    def delete_key(self, key_type: str, host: str, database: str | None = None) -> None:
        if key_type in ["user", "consumer"]:
            logger.warning(f"Attempt to delete {key_type} token for {host} ignored.")
            return
        else:
            cache_key = self.__cache_key(key_type, database)
            if host in self.__cache and cache_key in self.__cache[host]:
                del self.__cache[host][cache_key]
                self.save_cache()

    def get_user_credentials(self, host: str) -> tuple[str, str]:
        key = self.get_key("user", host)
        if key is None:
            raise KeyError(f"User credentials for {host} not found in secrets file")
        return key

    def get_consumer_key(self, host: str) -> tuple[str, str]:
        key = self.get_key("consumer", host)
        if key is None:
            raise KeyError(f"Consumer key for {host} not found in secrets file")
        return key

    def get_request_key(self, host: str, database: str) -> tuple[str, str] | None:
        key = self.get_key("request", host, database)
        if key is None:
            key = self.fetch_request_key(host, database)
            if key:
                self.set_key("request", host, key[0], key[1], database)
        return key

    def get_session_key(self, host: str, database: str) -> tuple[str, str] | None:
        key = self.get_key("session", host, database)
        if key is None:
            key = self.fetch_session_key(host, database)
            if key:
                self.set_key("session", host, key[0], key[1], database)
        return key

    def get_access_key(self, host: str, database: str) -> tuple[str, str] | None:
        key = self.get_key("access", host, database)
        if key is None:
            key = self.fetch_access_key(host, database)
            if key:
                self.set_key("access", host, key[0], key[1], database)
        return key

    def fetch_request_key(self, host: str, database: str) -> tuple[str, str]:
        logger.debug(f"Fetching request key for {host}...")
        consumer_key = self.get_consumer_key(host)
        service = create_oauth_service(
            consumer_key, self.__host_config[host]["REST_URL"], database
        )
        try:
            r = service.get_raw_request_token(params={"oauth_callback": "oob"})
            if r.status_code == 200:
                token = r.json()["oauth_token"]
                secret = r.json()["oauth_token_secret"]
                return token, secret
            elif r.status_code == 301:
                logger.error(
                    f"Failed to authenticate for request key on {host}: {r.text}"
                )
                raise Exception(
                    f"Unable to get aa request token due to authentication failure ({host}), check your credentials and consumer key+secret"
                )
            else:
                logger.error(
                    "Failed to get request token for %s (HTTP %s)",
                    host,
                    r.status_code,
                )
                raise Exception(f"Failed to get request token for {host}")
        except Exception as e:
            logger.error("Error getting request token: %s", e)
            raise Exception(f"Error getting request token for {host}")

    def fetch_session_key(
        self, host: str, database: str, retry: bool = True
    ) -> tuple[str, str]:
        logger.debug(f"Fetching session key for {host}...")
        access_key = self.get_access_key(host, database)
        if access_key is None:
            raise RuntimeError(f"Failed to obtain access key for {host} - {database}")
        consumer_key = self.get_consumer_key(host)
        session_request = OAuth1Session(
            consumer_key[0],
            consumer_key[1],
            access_token=access_key[0],
            access_token_secret=access_key[1],
        )
        url = f"{self.__host_config[host]['REST_URL']}/pubmlst_{database}_seqdef/oauth/get_session_token"
        r = session_request.get(url, params={})
        if r.status_code == 200:
            session_token = r.json()["oauth_token"]
            session_secret = r.json()["oauth_token_secret"]
        elif r.status_code in {301, 401} and retry:
            print(
                f"Session access denied. Attempting to regenerate keys as needed for {host}"
            )
            self.delete_key("access", host, database)
            session_token, session_secret = self.fetch_session_key(
                host, database, retry=False
            )
        else:
            print(f"{r.status_code}: Failed to get session token for {host}: {r.text}")
            raise Exception(
                f"Failed to get session token for {host} - {database}: "
                f"{r.status_code}: {r.text}"
            )
        return session_token, session_secret

    def fetch_access_key(self, host: str, database: str) -> tuple[str, str]:
        """Fetch an access key for the specified host and database. This will log in at the host as the user
        and get a verification code"""
        logger.debug(f"Fetching access key for {host}...")
        request_key = self.get_request_key(host, database)
        if request_key is None:
            raise RuntimeError(f"Failed to obtain request key for {host} - {database}")
        consumer_key = self.get_consumer_key(host)
        database_name = f"pubmlst_{database}_seqdef"

        """Automatically authorize the application."""
        logger.info(f"Authorising application for {host} - {database}...")
        session = self.__get_bigsdb_session(host)
        if not KeyCache.__logged_in(session, self.__host_config[host]["WEB_URL"]):
            raise Exception(f"Failed to log in to {host}")
        authorise_url = f"{self.__host_config[host]['WEB_URL']}?db={database_name}&page=authorizeClient&oauth_token={request_key[0]}"
        logger.debug(f"Authorise client URL: {authorise_url}")
        auth_response = session.get(authorise_url)
        if "The request token has already been redeemed" in auth_response.text:
            logger.info(
                "Request token has already been redeemed. Fetching a new token."
            )
            self.delete_key("request", host, database)
            return self.fetch_access_key(host, database)
        auth_soup = BeautifulSoup(auth_response.text, "html.parser")
        auth_form = self.__find_authorisation_form(auth_soup)

        # BIGSdb may return an account page here when the user has not yet
        # registered for this database.  Registration is safe to attempt even
        # if the page is a login form (for example, if the session expired).
        if auth_form is None and self.__ensure_database_registration(
            host, session, database_name
        ):
            auth_response = session.get(authorise_url)
            auth_soup = BeautifulSoup(auth_response.text, "html.parser")
            auth_form = self.__find_authorisation_form(auth_soup)
        if auth_form is None:
            logger.error("Could not find authorisation form")
            raise Exception(f"Failed to find authorisation form for {host}")

        auth_data = self.__hidden_inputs(auth_form)
        auth_data["submit"] = "Authorize"

        verifier_url = urljoin(auth_response.url, auth_form.get("action", ""))
        logger.debug(f"Verifier URL: {verifier_url}")
        final_response = session.post(
            verifier_url, data=auth_data, allow_redirects=True
        )

        final_soup = BeautifulSoup(final_response.text, "html.parser")
        verifier_tag = final_soup.find("b", string=re.compile(r"Verification code:"))
        verifier = ""
        if isinstance(verifier_tag, Tag):
            _, separator, verifier = verifier_tag.get_text(strip=True).partition(":")
            verifier = verifier.strip() if separator else ""
        if not verifier:
            logger.error("Failed to obtain verifier code from %s", final_response.url)
            raise Exception(f"Failed to obtain verifier code for {host}")

        logger.info(f"Getting access token for {host} - {database}...")
        service = create_oauth_service(
            consumer_key, self.__host_config[host]["REST_URL"], database
        )
        try:
            r = service.get_raw_access_token(
                request_key[0], request_key[1], params={"oauth_verifier": verifier}
            )
            if r.status_code == 200:
                token = r.json()["oauth_token"]
                secret = r.json()["oauth_token_secret"]
                return token, secret
            elif r.status_code == 301:
                self.delete_key("request", host, database)
                return self.fetch_access_key(host, database)
            else:
                logger.error(
                    "Failed to get access token for %s (HTTP %s)",
                    host,
                    r.status_code,
                )
                raise Exception(f"Failed to get access token for {host}")
        except Exception as e:
            logger.error(f"Error getting access token: {str(e)}")
            raise Exception(f"Error getting access token for {host}")

    @staticmethod
    def load_config(host_config_file: Path) -> dict[str, HostConfig]:
        if not host_config_file or not Path(host_config_file).exists():
            raise FileNotFoundError(
                f"Host configuration file not found: {host_config_file}"
            )
        with open(host_config_file, "r") as f:
            return cast(dict[str, HostConfig], json.load(f))

    @staticmethod
    def __logged_in(session: requests.Session, url: str) -> bool:
        """Check if the current session is logged in."""
        response = session.get(url)
        return "Log out" in response.text

    def __get_bigsdb_session(self, host: str) -> requests.Session:
        if host not in self.__logged_in_session or not KeyCache.__logged_in(
            self.__logged_in_session[host], self.__host_config[host]["WEB_URL"]
        ):
            self.__logged_in_session[host] = self.__login_to_bigsdb(host)
        return self.__logged_in_session[host]

    def __login_to_bigsdb(self, host: str) -> requests.Session:
        session = requests.Session()
        login_response = session.get(self.__host_config[host]["WEB_URL"])
        login_form = BeautifulSoup(login_response.text, "html.parser").find("form")

        if not isinstance(login_form, Tag):
            logger.error("Could not find login form")
            raise Exception(f"Failed to find login form for {host}")

        login_data = self.__hidden_inputs(login_form)

        user_credentials = self.get_user_credentials(host)

        login_data.update(
            {
                "user": user_credentials[0].strip(),
                # BIGSdb expects the raw password in this field over HTTPS.  The
                # server derives and verifies its own password hash.
                "password_field": user_credentials[1].strip(),
                "submit": "Log in",
                "page": "user",
            }
            | self.__host_config[host]["LOGIN_DB"]
        )

        login_response = session.post(
            urljoin(login_response.url, login_form.get("action", "")),
            data=login_data,
            allow_redirects=True,
        )

        if "Invalid username or password" in login_response.text:
            logger.error("Login failed: Invalid username/password")
            raise Exception(f"Invalid username/password for {host}")
        login_response.raise_for_status()
        logger.debug("Login successful")
        return session

    def get_rest_url(self, host: str) -> str:
        """Return the REST URL base for the specified host."""
        if host not in self.__host_config:
            raise KeyError(f"Host {host} not found in host configuration")
        return self.__host_config[host]["REST_URL"]

    @staticmethod
    def __find_authorisation_form(soup: BeautifulSoup) -> Tag | None:
        """Return the BIGSdb OAuth approval form from an authorisation page.

        Recent BIGSdb versions use the default CGI form action rather than an
        action containing ``authorizeClient``.  The OAuth hidden fields are a
        stable and unambiguous way to identify the form.
        """
        required_fields = {"db", "page", "oauth_token", "authorize"}
        for form in soup.find_all("form"):
            if not isinstance(form, Tag):
                continue
            fields = {
                name
                for field in form.find_all("input")
                if isinstance(field, Tag)
                if isinstance((name := field.get("name")), str)
            }
            if required_fields.issubset(fields):
                return form
        return None

    @staticmethod
    def __hidden_inputs(form: Tag) -> dict[str, str]:
        """Return hidden form fields with normalized string names and values."""
        hidden_data: dict[str, str] = {}
        for field in form.find_all("input", type="hidden"):
            if not isinstance(field, Tag):
                continue
            name = field.get("name")
            if not isinstance(name, str) or not name:
                continue

            value = field.get("value", "")
            if isinstance(value, str):
                hidden_data[name] = value
            elif isinstance(value, (list, tuple)):
                hidden_data[name] = " ".join(str(part) for part in value)
            else:
                hidden_data[name] = ""
        return hidden_data

    @staticmethod
    def __fieldset_contains(legend: Tag | None, database_name: str) -> bool:
        if legend is None or legend.parent is None:
            return False
        return database_name in legend.parent.get_text(" ", strip=True)

    def __ensure_database_registration(
        self, host: str, session: requests.Session, database_name: str
    ) -> bool:
        account_url = f"{self.__host_config[host]['WEB_URL']}?page=account"
        response = session.get(account_url)
        soup = BeautifulSoup(response.text, "html.parser")

        registered_legend = soup.find("legend", string=re.compile(r"^Registered$"))
        if isinstance(registered_legend, Tag) and self.__fieldset_contains(
            registered_legend, database_name
        ):
            return True

        auto_reg_form = next(
            (
                form
                for form in soup.find_all("form")
                if isinstance(form, Tag)
                and form.find("select", {"name": "auto_reg"}) is not None
            ),
            None,
        )
        auto_reg_select = (
            auto_reg_form.find("select", {"name": "auto_reg"})
            if isinstance(auto_reg_form, Tag)
            else None
        )
        if not isinstance(auto_reg_form, Tag) or not isinstance(auto_reg_select, Tag):
            logger.warning(
                f"Unable to find auto-registration form for {host} - {database_name}"
            )
            return False

        allowed_registrations: set[str] = set()
        for option in auto_reg_select.find_all("option"):
            if not isinstance(option, Tag):
                continue
            value = option.get("value", "")
            if isinstance(value, str):
                allowed_registrations.add(value)
        if database_name not in allowed_registrations:
            logger.warning(f"Account cannot auto-register for {host} - {database_name}")
            return False

        logger.info(f"Registering account for {host} - {database_name}...")
        register_data = self.__hidden_inputs(auto_reg_form)
        register_data.update({"auto_reg": database_name, "register": "Register"})
        # Current BIGSdb account forms use the default CGI action.  Keep the
        # requested page explicit when that action does not retain its query
        # string.
        register_data.setdefault("page", "account")
        register_response = session.post(
            urljoin(response.url, auto_reg_form.get("action", "")),
            data=register_data,
            allow_redirects=True,
        )
        register_soup = BeautifulSoup(register_response.text, "html.parser")
        registered_legend = register_soup.find(
            "legend", string=re.compile(r"^Registered$")
        )
        registered = isinstance(registered_legend, Tag) and self.__fieldset_contains(
            registered_legend, database_name
        )
        if not registered:
            logger.warning(
                f"Account registration did not complete for {host} - {database_name}"
            )
        return registered


def create_oauth_service(
    consumer_key: tuple[str, str], rest_url: str, database: str
) -> OAuth1Service:
    """Create and return an OAuth1Service instance."""
    return OAuth1Service(
        name="BIGSdb",
        consumer_key=consumer_key[0],
        consumer_secret=consumer_key[1],
        request_token_url=f"{rest_url}/pubmlst_{database}_seqdef/oauth/get_request_token",
        access_token_url=f"{rest_url}/pubmlst_{database}_seqdef/oauth/get_access_token",
        base_url=f"{rest_url}/pubmlst_{database}_seqdef",
    )
