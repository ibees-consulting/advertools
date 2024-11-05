import os
from scrapy_playwright.page import PageMethod
import advertools as adv

url_list = ['https://example.com', 'http://quotes.toscrape.com']

# Get the current file's directory
current_dir = os.path.dirname(os.path.abspath(__file__))
output_dir = os.path.join(current_dir, "output")

# Define PageMethod instances here
meta = {
    "playwright": True,
    "playwright_page_methods": [
        PageMethod("screenshot", path=output_dir, full_page=True, type="jpeg", quality=80),
    ],
}

custom_settings = {
    "DOWNLOAD_HANDLERS": {
        "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    },
    "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    'PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT': '100000',
    "PLAYWRIGHT_BROWSER_TYPE": "chromium",
    "PLAYWRIGHT_LAUNCH_OPTIONS": {
        "headless": True,
        "timeout": 20 * 1000,  # 20 seconds
    }
}

adv.save_screenshot(
    url_list=url_list,
    output_file=f"{output_dir}/output.jl",
    meta=meta,
    custom_settings=custom_settings
)