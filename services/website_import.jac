"""Bounded public-website import for business onboarding.

DNS answers are validated and the chosen public address is pinned to the socket;
TLS still verifies the original hostname. This prevents a second DNS lookup from
turning a public URL into a request to localhost or cloud metadata.
"""

import from html.parser { HTMLParser }
import http.client;
import ipaddress;
import json;
import re;
import socket;
import ssl;
import time;
import from urllib.parse { urljoin, urlsplit, urlunsplit }
import from urllib.robotparser { RobotFileParser }

glob MAX_BYTES: int = 524288,
     AGENT: str = "MLocalPreview/1.0";


def clean_url(value: str) -> str {
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\s\\\x00-\x1f]", value) {
        raise ValueError("Use a public https:// website address.");
    }
    try {
        parsed = urlsplit(value);
        host = (parsed.hostname or "").lower().encode("idna").decode("ascii");
        if (
            parsed.scheme != "https" or not host or parsed.username or parsed.password
            or parsed.port not in (None, 443) or "." not in host
            or host.endswith((".localhost", ".local", ".internal"))
        ) {
            raise ValueError();
        }
        ip: any = None;
        try {
            ip = ipaddress.ip_address(host);
        } except ValueError {
            ip = None;
        }
        if ip is not None and not ip.is_global {
            raise ValueError();
        }
        parts: tuple[str, str, str, str, str] = ("https", host, parsed.path or "/", parsed.query, "");
        return urlunsplit(parts);
    } except (ValueError, UnicodeError) {
        raise ValueError("Use a public https:// website address.") from None;
    }
}


def public_target(value: str) -> tuple[str, str, str] {
    url = clean_url(value);
    host = urlsplit(url).hostname or "";
    answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM);
    addresses = {str(answer[4][0]) for answer in answers};
    if not addresses or `any([not ipaddress.ip_address(ip).is_global for ip in addresses]) {
        raise ValueError("That website resolves to a private or reserved address.");
    }
    return (url, host, sorted(addresses)[0]);
}


"""HTTPS connection pinned to one validated address; TLS still checks the hostname.

http.client only calls connect() when no socket is attached, so attaching the
pinned TLS socket up front keeps the request on the validated address.
"""
def public_https(host: str, address: str) -> any {
    context = ssl.create_default_context();
    connection = http.client.HTTPSConnection(host, timeout=6, context=context);
    raw = socket.create_connection((address, 443), timeout=6);
    try {
        connection.sock = context.wrap_socket(raw, server_hostname=host);
    } except Exception as error {
        raw.close();
        raise error;
    }
    return connection;
}


def fetch_public(url: str, allowed: any = None) -> tuple[str, str, bytes] {
    deadline = time.monotonic() + 15;
    for _ in range(4) {
        if allowed is not None and not allowed(url) {
            raise ValueError("This website does not allow automated import of that page.");
        }
        (url, host, address) = public_target(url);
        parsed = urlsplit(url);
        connection = public_https(host, address);
        try {
            connection.request(
                "GET",
                parsed.path + ("?" + parsed.query if parsed.query else ""),
                headers={"User-Agent": AGENT, "Accept": "text/html,text/plain", "Accept-Encoding": "identity"}
            );
            response = connection.getresponse();
            if response.status in (301, 302, 303, 307, 308) {
                destination = clean_url(urljoin(url, response.getheader("Location", "")));
                # Cross-site redirects require a fresh user-supplied URL and robots check.
                if urlsplit(destination).hostname != host {
                    raise ValueError("This website redirects to another host. Paste its final https:// address.");
                }
                url = destination;
                continue;
            }
            if response.status == 404 and parsed.path == "/robots.txt" {
                return (url, "text/plain", b"");
            }
            if response.status != 200 {
                raise ValueError("The website did not allow the import. You can enter its details manually.");
            }
            if response.getheader("Content-Encoding", "identity") != "identity" {
                raise ValueError("This website returned an unsupported compressed page.");
            }
            length = response.getheader("Content-Length");
            if length and int(length) > MAX_BYTES {
                raise ValueError("This page is too large to import.");
            }
            data = bytearray();
            while len(data) <= MAX_BYTES {
                if time.monotonic() > deadline {
                    raise ValueError("This website took too long to respond.");
                }
                chunk = response.read1(min(16384, MAX_BYTES + 1 - len(data)));
                if not chunk {
                    break;
                }
                data.extend(chunk);
            }
            if len(data) > MAX_BYTES {
                raise ValueError("This page is too large to import.");
            }
            return (url, response.getheader("Content-Type", "").split(";")[0].lower(), bytes(data));
        } finally {
            connection.close();
        }
    }
    raise ValueError("This website redirected too many times.");
}


"""Collects visible text, title, meta tags, images, links and JSON-LD blocks."""
obj Page {
    has text: list[str] = [],
        title: list[str] = [],
        images: list[str] = [],
        links: list[list[str]] = [],
        meta: dict[str, str] = {},
        ld: list[any] = [],
        script: list[str] | None = None,
        hidden: int = 0,
        in_title: bool = False,
        link: list[str] | None = None;

    def feed(html: str) -> None {
        parser = HTMLParser(convert_charrefs=True);
        parser.handle_starttag = self.handle_starttag;
        parser.handle_data = self.handle_data;
        parser.handle_endtag = self.handle_endtag;
        parser.feed(html);
    }

    def handle_starttag(tag: str, pairs: any) -> None {
        attrs = dict(pairs);
        if tag in ("script", "style", "noscript") {
            self.hidden += 1;
            if tag == "script" and (attrs.get("type") or "").lower() == "application/ld+json" {
                self.script = [];
            }
        } elif tag == "title" {
            self.in_title = True;
        } elif tag == "meta" {
            self.meta[(attrs.get("property", attrs.get("name", "")) or "").lower()] = attrs.get("content", "");
        } elif tag == "img" {
            self.images.append(attrs.get("src", ""));
        } elif tag == "a" {
            self.link = [attrs.get("href", ""), ""];
        }
    }

    def handle_data(data: str) -> None {
        if self.script is not None {
            self.script.append(data);
        }
        if self.hidden {
            return;
        }
        if self.in_title {
            self.title.append(data);
        }
        if self.link is not None {
            self.link[1] += data;
        }
        self.text.append(data.strip());
    }

    def handle_endtag(tag: str) -> None {
        if tag in ("script", "style", "noscript") {
            if tag == "script" and self.script is not None {
                try {
                    self.ld.append(json.loads("".join(self.script)));
                } except (ValueError, RecursionError) {}
                self.script = None;
            }
            self.hidden = max(0, self.hidden - 1);
        }
        if tag == "title" {
            self.in_title = False;
        }
        if tag == "a" and self.link is not None {
            self.links.append(self.link);
            self.link = None;
        }
    }
}


def candidates(values: any, base: str) -> list[str] {
    result: list[str] = [];
    for value in values {
        if isinstance(value, dict) {
            value = value.get("url", value.get("contentUrl", ""));
        }
        if not isinstance(value, str) or not value {
            continue;
        }
        try {
            url = clean_url(urljoin(base, value));
            if url not in result {
                result.append(url);
            }
        } except ValueError {}
    }
    return result[:12];
}


def parse_page(html: str, url: str) -> dict[str, any] {
    page = Page();
    page.feed(html[:MAX_BYTES]);
    result: dict[str, any] = {
        "name": page.meta.get("og:site_name", "".join(page.title))[:160],
        "description": page.meta.get("description", page.meta.get("og:description", ""))[:1000],
        "cuisine": "",
        "address": "",
        "menu_text": "",
        "text": " ".join(page.text)[:20000]
    };
    logos: list[any] = [];
    images_ld: list[any] = [];
    menus: list[any] = [link[0] for link in page.links if "menu" in (link[0] + " " + link[1]).lower()];
    queue: list[any] = page.ld[:];
    for _ in range(100) {
        if not queue {
            break;
        }
        item = queue.pop(0);
        if isinstance(item, list) {
            queue.extend(item[:30]);
            continue;
        }
        if not isinstance(item, dict) {
            continue;
        }
        if "@graph" in item {
            queue.append(item["@graph"]);
        }
        kinds = item.get("@type", []);
        kinds = [kinds] if isinstance(kinds, str) else kinds;
        if not isinstance(kinds, list) or not set(kinds).intersection({"Restaurant", "CafeOrCoffeeShop", "FoodEstablishment", "LocalBusiness", "Bakery", "BarOrPub"}) {
            continue;
        }
        for (target, source) in (("name", "name"), ("description", "description"), ("cuisine", "servesCuisine")) {
            value = item.get(source, "");
            if isinstance(value, list) {
                value = ", ".join([v for v in value if isinstance(v, str)]);
            }
            if isinstance(value, str) and value {
                result[target] = value[:1000];
            }
        }
        address = item.get("address", "");
        if isinstance(address, dict) {
            address = ", ".join([str(address.get(k, "")) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode") if address.get(k)]);
        }
        if isinstance(address, str) {
            result["address"] = address[:500];
        }
        for (field, out) in (("logo", logos), ("image", images_ld), ("hasMenu", menus), ("menu", menus)) {
            value = item.get(field, []);
            out.extend(value if isinstance(value, list) else [value]);
        }
        break;
    }
    images = logos + [page.meta.get("og:image", "")] + images_ld + page.images;
    result["image_urls"] = candidates(images, url);
    result["image_url"] = result["image_urls"][0] if result["image_urls"] else "";
    result["menu_urls"] = candidates(menus, url);
    return result;
}


def collect_website(url: str, fetch: any = fetch_public) -> dict[str, any] {
    url = clean_url(url.strip());
    host = urlsplit(url).hostname or "";
    robots_url = f"https://{host}/robots.txt";
    (_, _, robot_data) = fetch(robots_url);
    robots = RobotFileParser();
    robots.parse(robot_data.decode("utf-8", errors="replace").splitlines());
    if not robots.can_fetch(AGENT, url) {
        raise ValueError("This website does not allow automated import. Enter its details manually.");
    }
    def allowed(dest: str) -> bool {
        return robots.can_fetch(AGENT, dest);
    }
    def guarded(target: str) -> any {
        return fetch_public(target, allowed);
    }
    reader = guarded if fetch is fetch_public else fetch;
    (final, content_type, data) = reader(url);
    if content_type not in ("text/html", "application/xhtml+xml") {
        raise ValueError("Paste the business homepage; PDF menus can be linked during review.");
    }
    if not robots.can_fetch(AGENT, final) {
        raise ValueError("This website does not allow automated import.");
    }
    result = parse_page(data.decode("utf-8", errors="replace"), final);
    result["website"] = final;
    result["sources"] = [final];
    # A single menu HTML page keeps latency, cost and website load bounded.
    for menu in result["menu_urls"] {
        if urlsplit(menu).hostname != host or urlsplit(menu).path.lower().endswith(".pdf") or not robots.can_fetch(AGENT, menu) {
            continue;
        }
        try {
            (menu_final, kind, body) = reader(menu);
            if kind == "text/html" and robots.can_fetch(AGENT, menu_final) {
                parsed = parse_page(body.decode("utf-8", errors="replace"), menu_final);
                result["text"] = (result["text"] + "\nMENU PAGE:\n" + parsed["text"])[:24000];
                result["menu_text"] = parsed["text"][:4000];
                chosen = result.get("image_url", "");
                result["image_urls"] = candidates(result["image_urls"] + parsed["image_urls"], final);
                if not chosen {
                    result["image_url"] = result["image_urls"][0] if result["image_urls"] else "";
                }
                result["sources"].append(menu_final);
            }
        } except (ValueError, OSError, http.client.HTTPException) {}
        break;
    }
    return result;
}
