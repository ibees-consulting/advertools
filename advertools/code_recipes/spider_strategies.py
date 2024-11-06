import os
from scrapy_playwright.page import PageMethod
import advertools as adv

url_list = ['https://example.com', 'http://quotes.toscrape.com']

# Get the current file's directory
current_dir = os.path.dirname(os.path.abspath(__file__))
output_dir = os.path.join(current_dir, "output")

adv.crawl(
    url_list=url_list,
    output_file=f"{output_dir}/output.jl",
)