import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from music_sync.config import load_config

DEFAULT_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def get_session(use_system_proxy: bool = None, headers: dict = None) -> requests.Session:
    cfg = load_config()
    if use_system_proxy is None:
        use_system_proxy = cfg.use_system_proxy

    session = requests.Session()
    session.trust_env = use_system_proxy

    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        raise_on_status=False
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    default_headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        default_headers.update(headers)
    session.headers.update(default_headers)

    return session
