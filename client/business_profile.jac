"""Public business details; claims stay in the existing offer detail flow."""
import from "react" { useEffect }
import from "./offer-image.jsx" { OfferImage }
import from .ui { ui, formSecondary, formHint }
import type from ..services.business_profile { BusinessProfileView }
import type from ..services.promo { OfferView }

def businessCash(value: float) -> str {
    # Intl has no Jac 0.37.23 browser stub; narrow its formatted result here.
    formatter = (window as any).Intl.NumberFormat("en-US", {"style": "currency", "currency": "USD", "maximumFractionDigits": 2});
    return formatter.format(value) as str;
}

def businessInitials(name: str) -> str {
    # JavaScript split accepts a regular expression; Jac's str stub does not.
    words = (name as any).split(new(RegExp, "\\s+")) as list[str];
    chosen = [word for word in words if word][:2];
    return "".join([word[0] for word in chosen]);
}

def BusinessOffer(item: OfferView, onOffer: Callable[[str], None], canOpenOffers: bool) -> JsxElement {
    tag = "button" if canOpenOffers else "article";
    controls: dict[str, any] = {"type": "button", "onClick": lambda { onOffer(item.id); }} if canOpenOffers else {};
    status = str(item.remaining) + " left · " + item.time_label if item.state == "active" else "Upcoming · " + item.time_label if item.state == "scheduled" else "Sold out" if item.state == "sold out" else item.state;
    return <@tag className="ml-business-offer" {**controls}>
        {if item.offer_image_url { <OfferImage url={item.offer_image_url} width="100%" height={160} alt={item.title}/> }}
        <span className="ml-business-offer-line"><span className="ml-business-offer-title">{item.title}</span><span className="ml-business-price">{businessCash(item.price)}</span></span>
        {if item.description { <span style={{"fontSize": 14, "lineHeight": 1.5, "color": ui.text}}>{item.description}</span> }}
        <span style={formHint}>{status}</span>
        {if canOpenOffers { <span style={{"fontSize": 13, "fontWeight": 800, "color": ui.navy}}>View offer →</span> }}
    </@tag>;
}

def:pub BusinessProfile(
    getProfile: Callable[[str, str], BusinessProfileView],
    onBack: Callable[[], None], onOffer: Callable[[str], None],
    slug: str = "", offerId: str = "", backLabel: str = "Back to offers", canOpenOffers: bool = True
) -> JsxElement {
    has profile: BusinessProfileView | None = None,
        phase: str = "loading",
        imageFailed: bool = False,
        attempt: int = 0,
        heading: Ref[HTMLElement] = Ref();

    # This effect owns its cancellation flag. Cleanup and its asynchronous
    # request must share the same closure when the selected business changes.
    useEffect(lambda {
        current = True;
        profile = None;
        phase = "loading";
        imageFailed = False;
        async def load {
            try {
                result = await getProfile(slug, offerId);
                if not current { return; }
                if not result or not result.ok { phase = "missing"; return; }
                if not isinstance(result.name, str) or not result.name.strip() or not Array.isArray(result.offers) {
                    raise Error("Invalid business response");
                }
                profile = result;
                phase = "ready";
            } except Exception {
                if current { phase = "error"; }
            }
        }
        load();
        return lambda { current = False; };
    }, [slug, offerId, getProfile, attempt]);

    can with [phase] entry {
        if phase == "ready" and heading.current { heading.current.focus({"preventScroll": True}); }
    }
    initials = businessInitials(profile.name) if profile else "";
    return <section className="ml-business" aria-label="Business profile">
        <style>{"""
            .ml-business{display:flex;flex-direction:column;gap:24px;padding:20px 24px 36px;color:var(--ml-ink);font-family:Figtree, system-ui, sans-serif;min-width:0}
            .ml-business h1,.ml-business h2,.ml-business p{margin:0}.ml-business h1{font-size:clamp(29px,7vw,44px);line-height:1.08;letter-spacing:-1.2px;font-weight:850;text-wrap:balance;overflow-wrap:anywhere}
            .ml-business h2{font-size:21px;letter-spacing:-.4px}.ml-business a{font-weight:750}
            .ml-business-back{align-self:flex-start;border:0;background:none;color:var(--ml-accent);padding:8px 0;font:inherit;font-weight:750;cursor:pointer;text-align:left}
            .ml-business-hero{background:var(--ml-ticket);color:var(--ml-ticket-text);padding:28px;border-radius:22px;display:flex;flex-direction:column;align-items:flex-start;gap:18px}
            .ml-business-monogram{display:grid;place-items:center;min-width:60px;height:60px;padding:0 10px;border-radius:16px;background:var(--ml-maize);color:var(--ml-on-maize);font-size:25px;font-weight:850;box-sizing:border-box}
            .ml-business-photo{width:100%;height:auto;aspect-ratio:3/2;object-fit:contain;border-radius:14px;background:var(--ml-sunken)}
            .ml-business-kicker{font-size:11px;font-weight:800;letter-spacing:1.6px;text-transform:uppercase}
            .ml-business-description{font-size:17px;line-height:1.65;max-width:60ch;overflow-wrap:anywhere;white-space:pre-wrap}
            .ml-business-grid{display:grid;gap:26px}.ml-business-section{display:flex;flex-direction:column;gap:14px;min-width:0}
            .ml-business-location{padding:22px;background:var(--ml-sunken);border-radius:18px;align-self:start}
            .ml-business-location address{font-style:normal;font-size:16px;line-height:1.6;white-space:pre-wrap;overflow-wrap:anywhere}
            .ml-business-note{border-top:1px solid var(--ml-border);padding-top:16px;display:flex;flex-direction:column;gap:8px}
            .ml-business-offers{display:flex;flex-direction:column;gap:12px}
            .ml-business-offer{display:flex;flex-direction:column;gap:10px;padding:20px;border:1px solid var(--ml-border);border-radius:16px;background:var(--ml-surface);color:var(--ml-ink);text-align:left;font:inherit;min-width:0;width:100%;box-sizing:border-box}
            button.ml-business-offer{cursor:pointer}.ml-business-offer-line{display:flex;justify-content:space-between;align-items:baseline;gap:16px}
            .ml-business-offer-title{font-weight:800;font-size:18px;overflow-wrap:anywhere}.ml-business-price{font-size:22px;font-weight:850;white-space:nowrap;color:var(--ml-accent)}
            .ml-business-empty{padding:22px 0;display:flex;flex-direction:column;gap:10px}.ml-business-state{padding:35px 0;display:flex;flex-direction:column;gap:16px}
            @media(min-width:700px){.ml-business-grid{grid-template-columns:minmax(0,1.4fr) minmax(0,1fr)}.ml-business-hero{padding:32px}}
            @media(max-width:359px){.ml-business{padding:16px 18px 30px}.ml-business-hero{padding:22px}.ml-business-offer-line{flex-wrap:wrap;gap:8px}}
        """}</style>
        <button type="button" className="ml-business-back" onClick={onBack}>{backLabel}</button>
        {if phase == "loading" {
            <div role="status" className="ml-business-state"><h2>Opening this business...</h2><p style={formHint}>Getting the latest details and offers.</p></div>
        }}
        {if phase == "error" or phase == "missing" {
            <div className="ml-business-state" role={"alert" if phase == "error" else "status"}>
                <h2>{"Could not load this business" if phase == "error" else "Business unavailable"}</h2>
                <p style={formHint}>{"Check your connection and try again." if phase == "error" else "This business could not be found. Return to offers to see what is available."}</p>
                <button type="button" style={formSecondary} onClick={lambda { attempt = attempt + 1; }}>Retry business profile</button>
            </div>
        }}
        {if phase == "ready" and profile {
            <header className="ml-business-hero">
                {if profile.image_url and not imageFailed { <img className="ml-business-photo" decoding="async" src={profile.image_url} alt={profile.name + " business photo"} referrerPolicy="no-referrer" onError={lambda { imageFailed = True; }} /> }
                else { <div className="ml-business-monogram" aria-hidden="true">{initials}</div> }}
                <div style={{"display": "flex", "flexDirection": "column", "gap": 10}}><p className="ml-business-kicker">{"Sample business" if profile.is_demo else "Local business"}</p><h1 tabIndex={-1} ref={heading}>{profile.name}</h1></div>
                {if profile.cuisine or profile.neighborhood { <p style={{"fontSize": 15, "lineHeight": 1.5}}>{" · ".join([label for label in [profile.cuisine, profile.neighborhood] if label])}</p> }}
            </header>
            if profile.blurb { <p className="ml-business-description">{profile.blurb}</p> }
            <div className="ml-business-grid">
                <section className="ml-business-section" aria-label="Business offers">
                    <div><h2>Offers from {profile.name}</h2><p style={{**formHint, "marginTop": 6}}>Current and upcoming offers, all in one place.</p></div>
                    <div className="ml-business-offers">
                        {if len(profile.offers) { for item in profile.offers { <BusinessOffer key={item.id} item={item} onOffer={onOffer} canOpenOffers={canOpenOffers} /> } }
                        else { <div className="ml-business-empty"><h2>No offers right now</h2><p style={formHint}>Check back for the next offer from this business.</p></div> }}
                    </div>
                </section>
                <section className="ml-business-section ml-business-location" aria-label="Business location"><h2>Find them nearby</h2>
                    {if profile.address {
                        <address>{profile.address}</address>
                        <a href={"https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent(profile.address)} target="_blank" rel="noopener noreferrer">Get directions ↗</a>
                    } else { <p style={formHint}>The business has not added an address yet.</p> }}
                    {if profile.entrance_note {
                        <div className="ml-business-note"><strong>Unverified restaurant note</strong><p style={{"fontSize": 14, "lineHeight": 1.6, "whiteSpace": "pre-wrap"}}>{profile.entrance_note}</p><p style={formHint}>{("Date provided: " + profile.note_date + ". ") if profile.note_date else ""}Not independently checked. Confirm current access with the restaurant.</p></div>
                    }}
                </section>
            </div>
        }}
    </section>;
}
