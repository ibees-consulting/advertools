import os
import json
import datetime
import subprocess
from urllib.parse import urlparse
import advertools as adv
from scrapy_playwright.page import PageMethod
from advertools.spider import MAX_CMD_LENGTH, _split_long_urllist

# URL list and directory setup
url_list = [
    'https://www.deluxeboxes.com/christmas-wrapping-paper-ideas-to-make-the-gift/',
    'https://svalbardi.com/blogs/water/benefit',
]

# url_list = [
#     'https://svalbardi.com',
#     'https://www.deluxeboxes.com'
# ]

# Directory to save screenshots
current_dir = os.path.dirname(os.path.abspath(__file__))
output_dir = os.path.join(current_dir, "output")
os.makedirs(output_dir, exist_ok=True)  # Ensure output directory exists

# PageMethod configuration
meta = {
    "playwright": True,
    "playwright_page_methods": [
        # Scroll down in increments and wait at each step
        PageMethod("evaluate", "window.scrollBy(0, window.innerHeight / 2)"),
        PageMethod("wait_for_timeout", 1000),  # Wait 1 second after each scroll
        PageMethod("evaluate", "window.scrollBy(0, window.innerHeight / 2)"),
        PageMethod("wait_for_timeout", 1000),
        PageMethod("evaluate", "window.scrollBy(0, window.innerHeight / 2)"),
        PageMethod("wait_for_timeout", 1000),
        PageMethod("evaluate", "window.scrollBy(0, window.innerHeight / 2)"),
        PageMethod("wait_for_timeout", 1000),
        
        # Final scroll to ensure the bottom of the page is reached
        PageMethod("evaluate", "window.scrollTo(0, document.body.scrollHeight)"),
        PageMethod("wait_for_timeout", 2000),  # Extra wait for any remaining content

        # Ensure all network requests are finished
        PageMethod("wait_for_load_state", "domcontentloaded"),

        # Take a full-page screenshot
        PageMethod("screenshot", path=output_dir, full_page=True, type="jpeg", quality=100),
    ],
}

# Custom settings for Scrapy Playwright integration
custom_settings = {
    "USER_AGENT": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko; Test) Chrome/129.0.0.0 Safari/537.36",
    "DOWNLOAD_HANDLERS": {
        "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    },
    "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    'PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT': '500000',
    "PLAYWRIGHT_BROWSER_TYPE": "chromium",
    "PLAYWRIGHT_LAUNCH_OPTIONS": {
        "headless": True,
        "timeout": 20 * 5000,
    }
}

# Helper functions and Spider class definition
# Define the Spider class with improvements for handling each URL uniquely
# (see your provided code for the complete structure here)

# Function to create the command for Scrapy
def create_command(url_list, meta, output_file, settings_list):
    # Basic scrapy command with url_list and meta as arguments, and output file specified
    base_command = ['scrapy', 'runspider', header_spider_path,
                    '-a', f'url_list={",".join(url_list)}',
                    '-a', f'meta={json.dumps(meta)}',
                    '-o', output_file]
    # Return the command with additional settings if any
    return base_command + settings_list

def save_screenshot(url_list, output_file, custom_settings=None, meta=None):
    # Convert a single URL from string to list
    if isinstance(url_list, str):
        url_list = [url_list]
    
    # Validate output file extension
    if os.path.splitext(output_file)[-1] != '.jl':
        raise ValueError("Please ensure your output_file ends with '.jl'.\n"
                         f"For example: {os.path.splitext(output_file)[0]}.jl")

    # Prepare custom settings list
    settings_list = []
    if custom_settings:
        for key, val in custom_settings.items():
            setting = '='.join([key, json.dumps(val)]) if isinstance(val, dict) else '='.join([key, str(val)])
            settings_list.extend(['-s', setting])

    # Assign default value to meta if none
    meta = meta or {"playwright": True}
    if "playwright_page_methods" in meta:
        meta["playwright_page_methods"] = [
            {"method": method.method, **method.kwargs}
            for method in meta["playwright_page_methods"]
        ]

    # Create the Scrapy command
    command = create_command(url_list, meta, output_file, settings_list)

    # Handle long URL lists by splitting
    if len(','.join(url_list)) > MAX_CMD_LENGTH:
        split_urls = _split_long_urllist(url_list)
        for u_list in split_urls:
            command[4] = f'url_list={",".join(u_list)}'
            result = subprocess.run(command)
            if result.returncode != 0:
                print(f"Error executing command: {result.stderr.decode()}")
    else:
        # Execute command normally
        result = subprocess.run(command)
        if result.returncode != 0:
            print(f"Error executing command: {result.stderr.decode()}")

# Run screenshot saving
adv.save_screenshot(url_list=url_list, output_file=f"{output_dir}/output.jl", meta=meta, custom_settings=custom_settings)
