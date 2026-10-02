"""Welcome, email verification and business setup in the Jac client."""
import from "react" { Fragment, useEffect }
import from .ui { BrandLogo, ThemeControl, uiFont, formStack, formInput, formButton, formSecondary, formHint }
import type from ..services.session { SessionView }
import type from ..services.onboarding { EmailCodeResult }
import type from ..services.business_onboarding { BusinessDraftView }

glob stack = formStack, inputStyle = formInput, button = formButton,
    secondary = formSecondary, hint = formHint,
    label = {**formStack, "gap": 6, "fontSize": 14, "fontWeight": 600};

def Notice(children: any = None) -> JsxElement {
    return (<p role="status" aria-live="polite" style={{**hint, "color": "var(--ml-accent)"}}>{children}</p>) if children else <Fragment/>;
}

def InputField(
    title: str, value: str, onChange: Callable[[ChangeEvent], None],
    placeholder: str = "", inputType: str = "text", autoComplete: str | None = None,
    maxLength: int = 0, required: bool = False, disabled: bool = False
) -> JsxElement {
    lengthProps = {"maxLength": maxLength} if maxLength > 0 else {};
    return <label style={label}>{title}<input style={inputStyle} value={value} onChange={onChange} placeholder={placeholder} type={inputType} autoComplete={autoComplete} {**lengthProps} required={required} disabled={disabled}/></label>;
}

def:pub audienceForSession(session: SessionView | None) -> str {
    if not session or not session.authenticated { return ""; }
    return "student" if session.role == "student" else "business" if session.role in ["business", "merchant"] else "";
}

def:pub AudienceWelcome(onChoose: Callable[[str], None]) -> JsxElement {
    choice = {**secondary, "textAlign": "left", "padding": "22px 20px", "display": "flex", "alignItems": "center", "justifyContent": "space-between", "gap": 16, "borderRadius": 20};
    return <main style={{"height": "100%", "overflowY": "auto", "background": "var(--ml-bg)", "fontFamily": uiFont, "color": "var(--ml-ink)"}}>
        <style>{".mlocal-choice:focus-visible{outline:3px solid var(--ml-focus);outline-offset:4px}.mlocal-choice:hover{filter:brightness(.97)}"}</style>
        <div style={{**stack, "boxSizing": "border-box", "minHeight": "100%", "maxWidth": 480, "margin": "0 auto", "padding": "36px 24px", "justifyContent": "center", "gap": 28}}>
            <div style={{"display": "flex", "alignItems": "center", "justifyContent": "space-between", "gap": 16, "flexWrap": "wrap"}}><BrandLogo/><ThemeControl/></div>
            <header style={{**stack, "gap": 12}}>
                <p style={{**hint, "fontWeight": 700}}>Welcome to M-Local</p>
                <h1 style={{"fontSize": 38, "lineHeight": 1.04, "letterSpacing": -1.2, "margin": 0, "fontWeight": 900}}>Good things are happening nearby.</h1>
                <p style={{**hint, "fontSize": 17}}>How will you join in?</p>
            </header>
            <div style={{**stack, "gap": 12}}>
                <button className="mlocal-choice ml-welcome-choice" type="button" style={{**choice, "background": "var(--ml-accent)", "borderColor": "var(--ml-accent)", "color": "var(--ml-accent-text)"}} onClick={lambda { onChoose("student"); }}>
                    <span style={{**stack, "gap": 8, "color": "inherit"}}><span style={{"fontSize": 21, "fontWeight": 750}}>Find local deals</span><span style={{"fontSize": 14, "lineHeight": 1.5, "fontWeight": 400}}>Join with your U-M email.<br/>Discover offers from local favorites.</span></span><span aria-hidden="true" style={{"fontSize": 26}}>→</span>
                </button>
                <button className="mlocal-choice ml-welcome-choice" type="button" style={choice} onClick={lambda { onChoose("business"); }}>
                    <span style={{**stack, "gap": 8, "color": "inherit"}}><span style={{"fontSize": 21, "fontWeight": 750}}>List my business</span><span style={{"fontSize": 14, "lineHeight": 1.5, "fontWeight": 400}}>Create your business profile.<br/>Connect with the U-M community.</span></span><span aria-hidden="true" style={{"fontSize": 26}}>→</span>
                </button>
            </div>
        </div>
    </main>;
}

def:pub EmailOnboarding(
    onSwitchAudience: Callable[[str], None],
    requestCode: Callable[[str, str, str], EmailCodeResult],
    verifyCode: Callable[[str, str], EmailCodeResult],
    onVerified: Callable[[str], None], onCancel: Callable[[], None],
    kind: str = "student", initialMode: str = "signin", cancelLabel: str = "Back",
    inputRef: Ref[HTMLInputElement] | None = None
) -> JsxElement {
    has name: str = "", value: str = "", mode: str = initialMode,
        code: str = "", challenge: EmailCodeResult | None = None, message: str = "",
        busy: bool = False, cooldown: int = 0,
        mounted: Ref[bool] = Ref(True), inFlight: Ref[bool] = Ref(False),
        codeRef: Ref[HTMLInputElement] = Ref(), emailRef: Ref[HTMLInputElement] = Ref(),
        revision: Ref[int] = Ref(0), previousKind: Ref[str] = Ref(kind);
    quiet = {"border": 0, "background": "transparent", "padding": "6px 0", "minHeight": 36, "color": "var(--ml-accent)", "font": "700 13px Figtree, system-ui", "cursor": "pointer", "textDecoration": "underline", "textUnderlineOffset": 3};

    useEffect(lambda {
        mounted.current = True;
        return lambda {
            mounted.current = False;
            revision.current = (revision.current or 0) + 1;
        };
    }, []);

    can with [kind] entry {
        if previousKind.current != kind {
            previousKind.current = kind;
            revision.current = (revision.current or 0) + 1;
            inFlight.current = False;
            busy = False;
            value = "";
            code = "";
            challenge = None;
            message = "";
            cooldown = 0;
        }
    }

    useEffect(lambda {
        if cooldown <= 0 { return; }
        timer = setTimeout(lambda { cooldown = max(0, cooldown - 1); }, 1000);
        return lambda { clearTimeout(timer); };
    }, [cooldown]);

    can with [challenge, kind] entry {
        target = codeRef.current if challenge else (inputRef.current if inputRef and inputRef.current else emailRef.current);
        if target { target.focus(); }
    }

    async def run(action: Callable[[Callable[[], bool]], None]) {
        if inFlight.current { return; }
        inFlight.current = True;
        busy = True;
        message = "";
        ticket = revision.current;
        def current() -> bool { return mounted.current == True and ticket == revision.current; }
        try { await action(current); }
        except Exception {
            if current() { message = "Could not connect. Your entries are kept; please try again."; }
        } finally {
            if current() { inFlight.current = False; busy = False; }
        }
    }

    async def sendAction(current: Callable[[], bool]) {
        reply = await requestCode(value.strip(), kind, name.strip() if mode == "signup" else "");
        if not current() { return; }
        message = "" if reply.ok else reply.message;
        if reply.ok {
            challenge = reply;
            code = "";
            cooldown = reply.retry_after or 60;
        }
    }

    async def verifyAction(current: Callable[[], bool]) {
        if not challenge { return; }
        reply = await verifyCode(challenge.challenge, code);
        if not current() { return; }
        if not reply.ok { message = reply.message; return; }
        await onVerified(reply.token);
    }
    async def send { await run(sendAction); }
    async def verify { await run(verifyAction); }
    def switchMode {
        mode = "signin" if mode == "signup" else "signup";
        message = "";
    }
    def submit(event: FormEvent) {
        event.preventDefault();
        if challenge { verify(); } else { send(); }
    }
    def changeEmail { challenge = None; code = ""; message = ""; }
    def changeCode(event: ChangeEvent) {
        digits = "";
        for character in event.target.value {
            if character in "0123456789" { digits += character; }
        }
        code = digits;
    }

    return <form aria-label={"Verify your email" if challenge else "Create an account" if mode == "signup" else "Sign in"} className="ml-auth" style={{**stack, "gap": 20}} onSubmit={submit}>
        <style>{".ml-auth button:focus-visible,.ml-auth select:focus-visible,.ml-auth input:focus-visible{outline:3px solid var(--ml-focus);outline-offset:3px}.ml-auth button:disabled{opacity:.55;cursor:default}.ml-auth select{max-width:100%}"}</style>
        <header style={{"display": "flex", "alignItems": "flex-start", "justifyContent": "space-between", "gap": 16}}>
            <div style={{**stack, "gap": 8}}>
                {(<select aria-label="Account type" value={kind} disabled={busy} onChange={lambda (e: ChangeEvent) { onSwitchAudience(e.target.value); }} style={{"font": "700 13px Figtree, system-ui", "color": "var(--ml-muted)", "border": "1px solid var(--ml-border)", "borderRadius": 6, "background": "var(--ml-bg)", "padding": "7px 9px"}}><option value="student">U-M student</option><option value="business">Business</option></select>) if not challenge else None}
                <h3 style={{"fontSize": 26, "lineHeight": 1.2, "margin": 0}}>{"Check your email" if challenge else "Create your account" if mode == "signup" else "Sign in"}</h3>
            </div>
            <button style={{**quiet, "whiteSpace": "nowrap", "color": "var(--ml-muted)"}} type="button" disabled={busy} onClick={onCancel}>{cancelLabel}</button>
        </header>
        {(<Fragment>
            <p style={hint}>{"Start with your name and email. We’ll send a code to verify it." if mode == "signup" else "Enter your email. We’ll send a code to sign you in."}</p>
            {(<InputField title={"Business Name" if kind == "business" else "Your name"} placeholder={"Business Name" if kind == "business" else "Your name"} autoComplete={"organization" if kind == "business" else "name"} maxLength={80} value={name} onChange={lambda (e: ChangeEvent) { name = e.target.value; }} required={True} disabled={busy}/>) if mode == "signup" else None}
            {(<label style={label}>U-M email
                <div style={{"display": "flex", "border": "1px solid var(--ml-border)", "borderRadius": 10, "overflow": "hidden", "minWidth": 0}}>
                    <input ref={inputRef or emailRef} aria-label="U-M uniqname" aria-describedby="umich-email-help" style={{**inputStyle, "border": 0, "borderRadius": 0, "flex": 1}} placeholder="uniqname" autoComplete="username" autoCapitalize="none" autoCorrect="off" spellCheck={False} pattern="[A-Za-z][A-Za-z0-9]{1,31}" maxLength={32} value={value} onChange={lambda (e: ChangeEvent) { value = e.target.value; }} required={True} disabled={busy}/>
                    <span style={{"padding": "13px 10px", "background": "var(--ml-sunken)", "color": "var(--ml-muted)", "fontWeight": 500, "whiteSpace": "nowrap"}}>@umich.edu</span>
                </div><span id="umich-email-help" style={hint}>Use your uniqname. No university password needed.</span>
            </label>) if kind == "student" else <label style={label}>Work email<input ref={inputRef or emailRef} style={inputStyle} placeholder="you@business.com" type="email" autoComplete="email" maxLength={254} value={value} onChange={lambda (e: ChangeEvent) { value = e.target.value; }} required={True} disabled={busy}/></label>}
            <Notice>{message}</Notice>
            <button type="submit" style={button} disabled={busy}>{"Sending..." if busy else "Send verification code"}</button>
            <p style={{**hint, "textAlign": "center"}}>{"Already registered? " if mode == "signup" else "New here? "}<button style={quiet} type="button" disabled={busy} onClick={switchMode}>{"Sign in" if mode == "signup" else "Create an account"}</button></p>
        </Fragment>) if not challenge else <Fragment>
            <p style={hint}>{"Enter the 6-digit code sent to "}<strong>{challenge.email}</strong>.</p>
            <label style={label}>Verification code<input ref={codeRef} style={{**inputStyle, "letterSpacing": 10, "fontSize": 28, "fontVariantNumeric": "tabular-nums", "textAlign": "center", "minHeight": 64}} aria-label="Verification code" placeholder="123456" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={changeCode} required={True} disabled={busy}/></label>
            <Notice>{message}</Notice>
            <button type="submit" style={button} disabled={busy}>{"Verifying..." if busy else "Verify and continue"}</button>
            <div style={{"display": "flex", "justifyContent": "space-between", "gap": 16, "flexWrap": "wrap"}}>
                <button style={quiet} type="button" disabled={busy} onClick={changeEmail}>Change email</button>
                <button style={quiet} type="button" disabled={busy or cooldown > 0} onClick={send}>{f"Resend code in {cooldown}s" if cooldown > 0 else "Resend code"}</button>
            </div><p style={hint}>The code expires in 10 minutes.</p>
        </Fragment>}
    </form>;
}

glob emptyDraft: dict[str, any] = {
    "name": "", "cuisine": "", "description": "", "address": "", "website": "",
    "menu_text": "", "menu_url": "", "image_url": "", "status": "draft",
    "image_urls": [], "menu_urls": [], "sources": []
};

def ImageChoice(url: str, selected: bool, disabled: bool, choose: Callable[[str], None]) -> JsxElement {
    return <button type="button" aria-label={"Use image " + url} disabled={disabled}
        onClick={lambda { choose(url); }}
        style={{"padding": 0, "border": "2px solid var(--ml-accent)" if selected else "1px solid var(--ml-border)", "borderRadius": 8, "background": "transparent", "width": 64, "height": 64, "overflow": "hidden"}}>
        <img src={url} alt="" width={64} height={64} referrerPolicy="no-referrer" style={{"width": 64, "height": 64, "objectFit": "cover", "display": "block"}} />
    </button>;
}


def:pub BusinessOnboarding(
    getDraft: Callable[[], BusinessDraftView],
    importWebsite: Callable[[str], BusinessDraftView],
    saveDraft: Callable[[str, str, str, str, str, str, str, str, bool], BusinessDraftView],
    onActivated: Callable[[], bool]
) -> JsxElement {
    has draft: BusinessDraftView = emptyDraft as BusinessDraftView,
        draftRef: Ref[BusinessDraftView] = Ref(emptyDraft as BusinessDraftView),
        message: str = "", busy: bool = False, confirmed: bool = False,
        ready: bool = False, loadFailed: bool = False,
        mounted: Ref[bool] = Ref(True), inFlight: Ref[bool] = Ref(False);

    # A ref preserves React's functional-update guarantee between batched edits.
    def replaceDraft(nextDraft: BusinessDraftView) {
        draftRef.current = nextDraft;
        draft = nextDraft;
    }

    async def load {
        if inFlight.current { return; }
        inFlight.current = True;
        ready = False;
        loadFailed = False;
        message = "";
        try {
            reply = await getDraft();
            if not mounted.current { return; }
            if reply.ok {
                replaceDraft({**emptyDraft, **reply} as BusinessDraftView);
                ready = True;
            } else {
                loadFailed = True;
                message = reply.message or "Could not load your saved profile.";
            }
        } except Exception {
            if mounted.current {
                loadFailed = True;
                message = "Could not load your saved profile. Retry before making changes.";
            }
        } finally { inFlight.current = False; }
    }

    useEffect(lambda {
        mounted.current = True;
        load();
        return lambda { mounted.current = False; };
    }, []);

    def field(key: str, value: str) {
        nextDraft = {**draftRef.current, "status": "draft"};
        nextDraft[key] = value;
        replaceDraft(nextDraft as BusinessDraftView);
        confirmed = False;
    }

    async def openManagement {
        try {
            opened = await onActivated();
            if not opened and mounted.current {
                message = "Your business profile was saved, but offer management could not be opened. Check your connection and try Open offer management.";
            }
        } except Exception {
            if mounted.current {
                message = "Your business profile was saved, but offer management could not be opened. Check your connection and try Open offer management.";
            }
        }
    }

    async def retryManagement {
        if inFlight.current { return; }
        inFlight.current = True;
        busy = True;
        message = "";
        try { await openManagement(); }
        finally { inFlight.current = False; if mounted.current { busy = False; } }
    }

    async def run(action: Callable[[], BusinessDraftView], activate: bool = False) {
        if inFlight.current { return; }
        inFlight.current = True;
        busy = True;
        message = "";
        try {
            reply = await action();
            if not mounted.current { return; }
            if reply.ok {
                replaceDraft({**emptyDraft, **reply} as BusinessDraftView);
                confirmed = False;
            }
            message = reply.message;
            if reply.ok and reply.status == "active" and activate { await openManagement(); }
        } except Exception {
            if mounted.current { message = "Could not connect. Your entries are kept; please retry."; }
        } finally { inFlight.current = False; if mounted.current { busy = False; } }
    }

    async def importCurrentWebsite() -> BusinessDraftView { return await importWebsite(draft.website); }
    async def saveCurrentDraft() -> BusinessDraftView {
        return await saveDraft(draft.name, draft.cuisine, draft.description, draft.address,
            draft.website, draft.menu_text, draft.menu_url, draft.image_url, confirmed);
    }
    def importSubmit(event: FormEvent) { event.preventDefault(); run(importCurrentWebsite); }
    def saveSubmit(event: FormEvent) { event.preventDefault(); run(saveCurrentDraft, True); }

    return <section aria-label="Create your business profile" style={{**stack, "paddingTop": 16, "borderTop": "1px solid var(--ml-border)"}}>
        <h3 style={{"margin": 0, "fontSize": 20}}>{"Your business profile" if draft.name else "Bring your business to M-Local"}</h3>
        {(<p role="status" style={hint}>Your saved details are here. Save your business profile to start posting.</p>) if draft.status == "pending_review" else None}
        {(<Fragment><p role="status" style={hint}>Your business profile is saved.</p><button style={secondary} type="button" disabled={busy} onClick={retryManagement}>{"Opening offer management..." if busy else "Open offer management"}</button></Fragment>) if draft.status == "active" else None}
        {(<p role="status" style={hint}>Loading your business profile...</p>) if not ready and not loadFailed else None}
        {(<button style={secondary} type="button" onClick={load}>Retry business profile</button>) if loadFailed else None}
        <p style={hint}>Start with your website. We’ll find details, menu links and image options for you to review. You can also fill this in yourself.</p>
        <form style={stack} onSubmit={importSubmit}>
            <InputField title="Business website" placeholder="https://your-business.com" inputType="url" value={draft.website} onChange={lambda (e: ChangeEvent) { field("website", e.target.value); }} disabled={busy or not ready} required={True}/>
            <button style={secondary} disabled={busy or not ready}>{"Working..." if busy else "Import website details"}</button>
        </form>
        <Notice>{message}</Notice>
        {(<div style={hint}>{"Sources: "}{[<Fragment key={url}>{" · " if i > 0 else ""}<a href={url} target="_blank" rel="noopener noreferrer">{"Website" if i == 0 else "Menu page"}</a></Fragment> for (i, url) in enumerate(draft.sources)]}</div>) if len(draft.sources) > 0 else None}
        <form style={stack} onSubmit={saveSubmit}>
            {(<img src={draft.image_url} alt={draft.name or "Business logo"} referrerPolicy="no-referrer" style={{"width": "100%", "height": 160, "objectFit": "cover", "display": "block", "background": "var(--ml-sunken)"}} />) if draft.image_url else None}
            {(<div style={{"display": "flex", "flexWrap": "wrap", "gap": 8}}>{[<ImageChoice key={url} url={url} selected={url == draft.image_url} disabled={busy} choose={lambda (picked: str) { field("image_url", picked); }} /> for url in draft.image_urls]}</div>) if len(draft.image_urls) > 0 else None}
            <InputField title="Image link" placeholder="https://your-business.com/photo.jpg" inputType="url" maxLength={2048} value={draft.image_url} onChange={lambda (e: ChangeEvent) { field("image_url", e.target.value); }} disabled={busy or not ready}/>
            <InputField title="Business name" placeholder="Business name" maxLength={120} value={draft.name} onChange={lambda (e: ChangeEvent) { field("name", e.target.value); }} required={True} disabled={busy or not ready}/>
            <InputField title="Cuisine" placeholder="Cuisine" maxLength={80} value={draft.cuisine} onChange={lambda (e: ChangeEvent) { field("cuisine", e.target.value); }} disabled={busy or not ready}/>
            <InputField title="Street address" placeholder="Street address" maxLength={240} value={draft.address} onChange={lambda (e: ChangeEvent) { field("address", e.target.value); }} required={True} disabled={busy or not ready}/>
            <label style={label}>About your business<textarea style={{**inputStyle, "minHeight": 90, "resize": "vertical"}} placeholder="About your business" maxLength={1000} value={draft.description} onChange={lambda (e: ChangeEvent) { field("description", e.target.value); }} disabled={busy or not ready}/></label>
            <label style={label}>Menu notes to review<textarea style={{**inputStyle, "minHeight": 120, "resize": "vertical"}} placeholder="Menu items and prices" maxLength={4000} value={draft.menu_text} onChange={lambda (e: ChangeEvent) { field("menu_text", e.target.value); }} disabled={busy or not ready}/></label>
            <p style={hint}>Check item names and prices against your current menu. These notes do not create offers.</p>
            {(<label style={label}>Found menu links<select style={inputStyle} value={draft.menu_url} onChange={lambda (e: ChangeEvent) { field("menu_url", e.target.value); }} disabled={busy}><option value="">Choose a menu link</option>{[<option key={url} value={url}>{url}</option> for url in draft.menu_urls]}</select></label>) if len(draft.menu_urls) > 0 else None}
            <InputField title="Menu link" placeholder="https://your-business.com/menu" inputType="url" maxLength={2048} value={draft.menu_url} onChange={lambda (e: ChangeEvent) { field("menu_url", e.target.value); }} disabled={busy or not ready}/>
            <label style={{**hint, "display": "flex", "gap": 10, "alignItems": "flex-start", "minHeight": 44}}><input type="checkbox" checked={confirmed} onChange={lambda (e: ChangeEvent) { confirmed = e.target.checked; }} disabled={busy or not ready} style={{"width": 20, "height": 20, "flexShrink": 0}}/>I can represent this business and have permission to use the details and selected image.</label>
            <button style={button} disabled={busy or not ready or not confirmed}>{"Saving..." if busy else "Save business profile"}</button>
            <p style={hint}>Save your business profile to start posting. You can then create offers and edit your business details from Manage.</p>
        </form>
    </section>;
}
