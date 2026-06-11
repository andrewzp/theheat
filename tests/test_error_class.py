from src.data.error_class import classify_error_class


def test_classify_error_class_taxonomy():
    cases = {
        None: "none",
        "": "none",
        "FIRMS fetch failed: 401 Client Error: Unauthorized": "auth",
        "EARTHDATA_TOKEN appears to have expired": "auth",
        "JTWC fetch failed: 403 Client Error: Forbidden for url: https://www.metoc.navy.mil/jtwc/rs...": "http403",
        "Open-Meteo fetch failed: 429 Client Error: Too Many Requests for url: https://api.open-meteo.com/...": "http429",
        "Ice mass fetch failed: 502 Server Error: Bad Gateway for url: https://archive.podaac.earthdata.nasa.gov/...": "http5xx",
        "GPM IMERG fetch hit 3 repeated ConnectTimeout failures for 2026-06-08; first error: ConnectTimeout": "timeout",
        "NameResolutionError: getaddrinfo failed for climate.example.test": "dns",
        "GDACS fetch failed: HTTPSConnectionPool(host='www.gdacs.org', port=443): Max retries exceeded": "connection",
        "JSONDecodeError: Expecting value: line 1 column 1 (char 0)": "parse",
        "50 air-quality city fetches failed": "other",
    }

    for error, expected in cases.items():
        assert classify_error_class(error) == expected, error
