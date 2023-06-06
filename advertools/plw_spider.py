import datetime
import json
import logging
from pathlib import Path
import platform
import re
import subprocess
from functools import reduce
from urllib.parse import parse_qs, urlparse, urlsplit
import pandas as pd
import scrapy
import scrapy.logformatter as formatter
from scrapy import Request
from scrapy.linkextractors import LinkExtractor
from scrapy.spiders import Spider
from scrapy.utils.response import get_base_url
from scrapy_playwright.page import PageMethod

import advertools as adv


if int(pd.__version__[0]) >= 1:
    from pandas import json_normalize
else:
    from pandas.io.json import json_normalize

from advertools import __version__ as adv_version

spider_path = adv.__path__[0] + '/plw_spider.py'

user_agent = f'advertools/{adv_version}'

BODY_TEXT_SELECTOR = '//body//span//text() | //body//p//text() | //body//li//text()'

_IMG_ATTRS = {'alt', 'crossorigin', 'height', 'ismap', 'loading', 'longdesc',
              'referrerpolicy', 'sizes', 'src', 'srcset', 'usemap', 'width'}


def _crawl_or_not(url,
                  exclude_url_params=None,
                  include_url_params=None,
                  exclude_url_regex=None,
                  include_url_regex=None):
    qs = parse_qs(urlsplit(url).query)
    supplied_conditions = []
    if exclude_url_params is not None:
        if exclude_url_params is True and qs:
            return False
        if exclude_url_params is True and not qs:
            pass
        else:
            exclude_params_in_url = not bool(set(exclude_url_params).intersection(qs))
            supplied_conditions.append(exclude_params_in_url)

    if include_url_params is not None:
        include_params_in_url = bool(set(include_url_params).intersection(qs))
        supplied_conditions.append(include_params_in_url)

    if exclude_url_regex is not None:
        exclude_pattern_matched = not bool(re.findall(exclude_url_regex, url))
        supplied_conditions.append(exclude_pattern_matched)

    if include_url_regex is not None:
        include_pattern_matched = bool(re.findall(include_url_regex, url))
        supplied_conditions.append(include_pattern_matched)
    return all(supplied_conditions)

def _extract_images(response):
    page_has_images = response.xpath('//img')
    if page_has_images:
        img_attributes = reduce(set.union,
                                [set(x.attrib.keys())
                                 for x in page_has_images])
        img_attributes = img_attributes.intersection(_IMG_ATTRS)
        d = dict()
        for im_attr in img_attributes:
            d['img_' + im_attr] = '@@'.join([im.attrib.get(im_attr) or ''
                                            for im in response.xpath('//img')])
        return d
    return {}


def get_max_cmd_len():
    system = platform.system()
    cmd_dict = {'Windows': 7000, 'Linux': 100000, 'Darwin': 100000}
    if system in cmd_dict:
        return cmd_dict[system]
    return 6000


MAX_CMD_LENGTH = get_max_cmd_len()

formatter.SCRAPEDMSG = "Scraped from %(src)s"
formatter.DROPPEDMSG = "Dropped: %(exception)s"
formatter.DOWNLOADERRORMSG_LONG = "Error downloading %(request)s"


class MyLinkExtractor(LinkExtractor):
    def extract_links(self, response):
        base_url = get_base_url(response)
        if self.restrict_xpaths:
            docs = [
                subdoc
                for x in self.restrict_xpaths
                for subdoc in response.xpath(x)
            ]
        else:
            docs = [response.selector]
        all_links = []
        for doc in docs:
            links = self._extract_links(doc, response.url, response.encoding,
                                        base_url)
            all_links.extend(self._process_links(links))
        return all_links


le = MyLinkExtractor(unique=False)
le_nav = MyLinkExtractor(unique=False, restrict_xpaths='//nav')
le_header = MyLinkExtractor(unique=False, restrict_xpaths='//header')
le_footer = MyLinkExtractor(unique=False, restrict_xpaths='//footer')

crawl_headers = {
    'url',
    'title',
    'meta_desc',
    'viewport',
    'charset',
    'alt_href',
    'alt_hreflang',
    'h1',
    'h2',
    'h3',
    'h4',
    'h5',
    'h6',
    'canonical',
    'body_text',
    'size',
    'download_timeout',
    'download_slot',
    'download_latency',
    'redirect_times',
    'redirect_ttl',
    'redirect_urls',
    'redirect_reasons',
    'depth',
    'status',
    'links_url',
    'links_text',
    'links_nofollow',
    'img_src',
    'img_alt',
    'ip_address',
    'crawl_time',
    'blocked_by_robotstxt',
    'jsonld_errors',
    'request_headers_accept',
    'request_headers_accept-language',
    'request_headers_user-agent',
    'request_headers_accept-encoding',
    'request_headers_cookie',
}


def _split_long_urllist(url_list, max_len=MAX_CMD_LENGTH):
    """Split url_list if their total length is greater than MAX_CMD_LENGTH."""
    split_list = [[]]

    for u in url_list:
        temp_len = sum(len(temp_u) for temp_u in split_list[-1])
        if (temp_len < max_len) and (temp_len + len(u) < max_len):
            split_list[-1].append(u)
        else:
            split_list.append([u])
    return split_list


def _numbered_duplicates(items):
    """Append a number to all duplicated items starting at 1.

    ['og:site', 'og:image', 'og:image', 'og:type', 'og:image']
    becomes:
    ['og:site', 'og:image_1', 'og:image_2', 'og:type', 'og:image_3']
    """
    item_count = dict.fromkeys(items, 0)
    numbered_items = []
    for item in items:
        numbered_items.append(item + '_' + str(item_count[item]))
        item_count[item] += 1
    for i, num_item in enumerate(numbered_items):
        split_number = num_item.rsplit('_', maxsplit=1)
        if split_number[1] == '0':
            numbered_items[i] = split_number[0]
    return numbered_items


def _json_to_dict(jsonobj, i=None):
    try:
        df = json_normalize(jsonobj)
        if i:
            df = df.add_prefix('jsonld_{}_'.format(i))
        else:
            df = df.add_prefix('jsonld_')
        return dict(zip(df.columns, df.values[0]))
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(msg=str(e))
        return {}


tags_xpaths = {
    'title': '//title/text()',
    'meta_desc': '//meta[@name="description"]/@content',
    'viewport': '//meta[@name="viewport"]/@content',
    'charset': '//meta[@charset]/@charset',
    'h1': '//h1',
    'h2': '//h2',
    'h3': '//h3',
    'h4': '//h4',
    'h5': '//h5',
    'h6': '//h6',
    'canonical': '//link[@rel="canonical"]/@href',
    'alt_href': '//link[@rel="alternate"]/@href',
    'alt_hreflang': '//link[@rel="alternate"]/@hreflang',
}


def _extract_content(resp, **tags_xpaths):
    d = {}
    for tag, xpath in tags_xpaths.items():
        if not tag.startswith('h'):
            value = '@@'.join(resp.xpath(xpath).getall())
            if value:
                d.update({tag: value})
        else:
            value = '@@'.join([h.root.text_content()
                               for h in resp.xpath(xpath)])
            if value:
                d.update({tag: value})
    return d


class SEOSitemapPlwSpider(Spider):
    name = 'seo_plw_spider'
    follow_links = False
    skip_url_params = False
    css_selectors = {}
    xpath_selectors = {}
    custom_settings = {
        'USER_AGENT': user_agent,
        'ROBOTSTXT_OBEY': True,
        'HTTPERROR_ALLOW_ALL': True,
    }

    def __init__(self, url_list, follow_links=False,
                 allowed_domains=None,
                 exclude_url_params=None,
                 include_url_params=None,
                 exclude_url_regex=None,
                 include_url_regex=None,
                 css_selectors=None,
                 xpath_selectors=None,
                 meta=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_urls = json.loads(json.dumps(url_list.split(',')))
        self.allowed_domains = json.loads(json.dumps(allowed_domains.split(',')))
        self.follow_links = eval(json.loads(json.dumps(follow_links)))
        self.exclude_url_params = eval(json.loads(json.dumps(exclude_url_params)))
        self.include_url_params = eval(json.loads(json.dumps(include_url_params)))
        self.exclude_url_regex = str(json.loads(json.dumps(exclude_url_regex)))
        if self.exclude_url_regex == "None":
            self.exclude_url_regex = None
        self.include_url_regex = str(json.loads(json.dumps(include_url_regex)))
        if self.include_url_regex == "None":
            self.include_url_regex = None
        self.css_selectors = eval(json.loads(json.dumps(css_selectors)))
        self.xpath_selectors = eval(json.loads(json.dumps(xpath_selectors)))
        self.meta = json.loads(meta)
    
    def update_page_methods(self, meta):
        if "playwright_page_methods" in meta:
            # Reconstruct PageMethod instances
            meta["playwright_page_methods"] = [
                PageMethod(data.pop("method"), **data)
                for data in meta["playwright_page_methods"]
            ]
        return meta
    
    def normalize_url(self, url):
        parsed_url = urlparse(url)
        domain = parsed_url.netloc
        normalized_url = domain.split(".")[-2]
        return normalized_url
    
    def update_meta(self, url):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if "playwright_page_methods" in self.meta:
            for method in self.meta["playwright_page_methods"]:
                if method.method == "screenshot":
                    # Get the screenshot_dir from the "screenshot" method
                    screenshot_dir = method.kwargs.get("path", "")
                    # Generate unique filename for the current URL
                    normalized_url = self.normalize_url(url)
                    filename = f"{screenshot_dir}/{normalized_url}-{timestamp}.jpeg"
                    # Create a new meta dictionary for each URL iteration
                    updated_meta = self.meta.copy()
                    # Create a new method kwargs dictionary to avoid modifying the original one
                    new_kwargs = method.kwargs.copy()
                    # Update the path value in the new_kwargs dictionary
                    new_kwargs["path"] = filename
                    # Update the meta dictionary with the modified method kwargs
                    updated_meta["playwright_page_methods"] = [PageMethod(method.method, **new_kwargs)]

                    return updated_meta
        else:
            return self.meta

    def start_requests(self):
        # Update the meta with the appropriate PageMethod instances
        self.meta = self.update_page_methods(self.meta)
        for url in self.start_urls:
            try:
                updated_meta = self.update_meta(url)
                yield Request(url, meta=updated_meta, callback=self.parse, errback=self.errback)
            except Exception as e:
                self.logger.error(repr(e))

    def errback(self, failure):
        if not failure.check(scrapy.exceptions.IgnoreRequest):
            self.logger.error(repr(failure))
            yield {'url': failure.request.url,
                   'crawl_time': datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                   'errors': repr(failure)}

    def parse(self, response):
        links = le.extract_links(response)
        nav_links = le_nav.extract_links(response)
        header_links = le_header.extract_links(response)
        footer_links = le_footer.extract_links(response)
        images = _extract_images(response)
        if links:
            parsed_links = dict(
                links_url='@@'.join(link.url for link in links),
                links_text='@@'.join(link.text for link in links),
                links_nofollow='@@'.join(str(link.nofollow) for link in links),
            )
        else:
            parsed_links = {}
        if nav_links:
            parsed_nav_links = dict(
                nav_links_url='@@'.join(link.url for link in nav_links),
                nav_links_text='@@'.join(link.text for link in nav_links),
                nav_links_nofollow='@@'.join(str(link.nofollow)
                                             for link in nav_links),
            )
        else:
            parsed_nav_links = {}
        if header_links:
            parsed_header_links = dict(
                header_links_url='@@'.join(link.url
                                           for link in header_links),
                header_links_text='@@'.join(link.text
                                            for link in header_links),
                header_links_nofollow='@@'.join(str(link.nofollow)
                                                for link in header_links),
            )
        else:
            parsed_header_links = {}
        if footer_links:
            parsed_footer_links = dict(
                footer_links_url='@@'.join(link.url for link in footer_links),
                footer_links_text='@@'.join(link.text
                                            for link in footer_links),
                footer_links_nofollow='@@'.join(str(link.nofollow)
                                                for link in footer_links),
            )
        else:
            parsed_footer_links = {}
        if self.css_selectors:
            css_selectors = {key: '@@'.join(response.css('{}'.format(val)).getall())
                             for key, val in self.css_selectors.items()}
            css_selectors = {k: v for k, v in css_selectors.items() if v}
        else:
            css_selectors = {}

        if self.xpath_selectors:
            xpath_selectors = {key: '@@'.join(response.xpath('{}'.format(val)).getall())
                               for key, val in self.xpath_selectors.items()}
            xpath_selectors = {k: v for k, v in xpath_selectors.items() if v}
        else:
            xpath_selectors = {}
        canonical = {'canonical': '@@'.join(response.css('link[rel="canonical"]::attr(href)').getall())}
        canonical = canonical if canonical.get('canonical') else {}
        alt_href = {'alt_href': '@@'.join(response.css('link[rel=alternate]::attr(href)').getall())}
        alt_href = alt_href if alt_href.get('alt_href') else {}
        alt_hreflang = {'alt_hreflang': '@@'.join(response.css('link[rel=alternate]::attr(hreflang)').getall())}
        alt_hreflang = alt_hreflang if alt_hreflang.get('alt_hreflang') else {}
        og_props = response.xpath('//meta[starts-with(@property, "og:")]/@property').getall()
        og_content = response.xpath('//meta[starts-with(@property, "og:")]/@content').getall()
        if og_props and og_content:
            og_props = _numbered_duplicates(og_props)
            open_graph = dict(zip(og_props, og_content))
        else:
            open_graph = {}
        twtr_names = response.xpath('//meta[starts-with(@name, "twitter:")]/@name').getall()
        twtr_content = response.xpath('//meta[starts-with(@name, "twitter:")]/@content').getall()
        if twtr_names and twtr_content:
            twtr_card = dict(zip(twtr_names, twtr_content))
        else:
            twtr_card = {}
        try:
            ld = [json.loads(s.replace('\r', '')) for s in
                  response.css('script[type="application/ld+json"]::text').getall()]
            if not ld:
                jsonld = {}
            else:
                if len(ld) == 1:
                    if isinstance(ld, list):
                        ld = ld[0]
                    jsonld = _json_to_dict(ld)
                else:
                    ld_norm = [_json_to_dict(x, i) for i, x in enumerate(ld)]
                    jsonld = {}
                    for norm in ld_norm:
                        jsonld.update(**norm)
        except Exception as e:
            jsonld = {'jsonld_errors': str(e)}
            self.logger.exception(' '.join([str(e), str(response.status),
                                            response.url]))
        page_content = _extract_content(response, **tags_xpaths)
        

        yield dict(
            url=response.request.url,
            **page_content,
            **open_graph,
            **twtr_card,
            **jsonld,
            body_text=' '.join(response.xpath(BODY_TEXT_SELECTOR).extract()),
            size=len(response.body),
            **css_selectors,
            **xpath_selectors,
            **{k: '@@'.join(str(val) for val in v) if isinstance(v, list)
               else v for k, v in response.meta.items() if k != 'playwright_page_methods'},
            status=response.status,
            **parsed_links,
            **parsed_nav_links,
            **parsed_header_links,
            **parsed_footer_links,
            **images,
            ip_address=str(response.ip_address),
            crawl_time=datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            **{'resp_headers_' + k: v
               for k, v in response.headers.to_unicode_dict().items()},
            **{'request_headers_' + k: v
               for k, v in response.request.headers.to_unicode_dict().items()},
        )
        if self.follow_links:
            next_pages = [link.url for link in links]
            if next_pages:
                for page in next_pages:
                    cond = _crawl_or_not(
                        page,
                        exclude_url_params=self.exclude_url_params,
                        include_url_params=self.include_url_params,
                        exclude_url_regex=self.exclude_url_regex,
                        include_url_regex=self.include_url_regex)
                    if cond:
                        updated_meta = self.update_meta(page)
                        yield Request(page, callback=self.parse, meta=updated_meta,
                                      errback=self.errback)
                    # if self.skip_url_params and urlparse(page).query:
                    #     continue


def plw_crawl(url_list, output_file, follow_links=False,
          allowed_domains=None,
          exclude_url_params=None,
          include_url_params=None,
          exclude_url_regex=None,
          include_url_regex=None,
          css_selectors=None, xpath_selectors=None, custom_settings=None, meta=None
          ):
    if isinstance(url_list, str):
        url_list = [url_list]
    if isinstance(allowed_domains, str):
        allowed_domains = [allowed_domains]
    if output_file.rsplit('.')[-1] != 'jl':
        raise ValueError("Please make sure your output_file ends with '.jl'.\n"
                         "For example:\n"
                         "{}.jl".format(output_file.rsplit('.', maxsplit=1)[0]))
    if (xpath_selectors is not None) and (css_selectors is not None):
        css_xpath = set(xpath_selectors).intersection(css_selectors)
        if css_xpath:
            raise ValueError("Please make sure you don't set common keys for"
                             "`css_selectors` and `xpath_selectors`.\n"
                             "Duplicated keys: {}".format(css_xpath))
    for selector in [xpath_selectors, css_selectors]:
        if selector is not None and set(selector).intersection(crawl_headers):
            raise ValueError("Please make sure you don't use names of default "
                             "headers. Avoid using any of these as keys: \n"
                             "{}".format(sorted(crawl_headers)))
    if allowed_domains is None:
        allowed_domains = {urlparse(url).netloc for url in url_list}
    if exclude_url_params is not None and include_url_params is not None:
        if exclude_url_params is True:
            raise ValueError("Please make sure you don't exclude and include "
                             "parameters at the same time.")
        common_params = set(exclude_url_params).intersection(include_url_params)
        if common_params:
            raise ValueError(f"Please make sure you don't include and exclude "
                             f"the same parameters.\n"
                             f"Common parameters entered: "
                             f"{', '.join(common_params)}")
    if include_url_regex is not None and exclude_url_regex is not None:
        if include_url_regex == exclude_url_regex:
            raise ValueError(f"Please make sure you don't include and exclude "
                             f"the same regex pattern.\n"
                             f"You entered '{include_url_regex}'.")

    # default meta data if none provided
    if meta is None:
        meta = {"playwright": True}
    # Convert PageMethod objects into dictionaries
    if "playwright_page_methods" in meta:
        meta["playwright_page_methods"] = [
            {"method": method.method, **method.kwargs}
            for method in meta["playwright_page_methods"]
        ]
    
    settings_list = []
    if custom_settings is not None:
        for key, val in custom_settings.items():
            if isinstance(val, (dict, list, set, tuple)):
                setting = '='.join([key, json.dumps(val)])
            else:
                setting = '='.join([key, str(val)])
            settings_list.extend(['-s', setting])

    command = ['scrapy', 'runspider', spider_path,
               '-a', 'url_list=' + ','.join(url_list),
               '-a', 'allowed_domains=' + ','.join(allowed_domains),
               '-a', 'follow_links=' + str(follow_links),
               '-a', 'exclude_url_params=' + str(exclude_url_params),
               '-a', 'include_url_params=' + str(include_url_params),
               '-a', 'exclude_url_regex=' + str(exclude_url_regex),
               '-a', 'include_url_regex=' + str(include_url_regex),
               '-a', 'css_selectors=' + str(css_selectors),
               '-a', 'xpath_selectors=' + str(xpath_selectors),
               '-a', 'meta=' + json.dumps(meta),
               '-o', output_file] + settings_list
    if len(','.join(url_list)) > MAX_CMD_LENGTH:
        split_urls = _split_long_urllist(url_list)

        for u_list in split_urls:
            command[4] = 'url_list=' + ','.join(u_list)
            subprocess.run(command)
    else:
        subprocess.run(command)