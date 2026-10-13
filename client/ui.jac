"""Shared themed presentation primitives for the Jac phone interface."""
import from "react" { Fragment, useLayoutEffect, useSyncExternalStore }
import from "./theme.mjs" { createThemeStore }
import from "./app-opener.jsx" { AppOpener }
import from "./document-head.jsx" { DocumentHead }

obj UiColors {
    has ink: str = "var(--ml-ink)", navy: str = "var(--ml-accent)",
        paper: str = "var(--ml-bg)", white: str = "var(--ml-surface)",
        muted: str = "var(--ml-muted)", line: str = "var(--ml-border)",
        inset: str = "var(--ml-sunken)", maize: str = "var(--ml-maize)",
        text: str = "var(--ml-text)", accentText: str = "var(--ml-accent-text)",
        accentSoft: str = "var(--ml-accent-soft)", good: str = "var(--ml-good)",
        goodSoft: str = "var(--ml-good-soft)", warn: str = "var(--ml-warn)",
        warnSoft: str = "var(--ml-warn-soft)", bad: str = "var(--ml-bad)",
        badSoft: str = "var(--ml-bad-soft)", focus: str = "var(--ml-focus)",
        ticket: str = "var(--ml-ticket)", ticketText: str = "var(--ml-ticket-text)",
        onMaize: str = "var(--ml-on-maize)";
}

obj ThemeSnapshot {
    has preference: str = "system", resolved: str = "light";
}

glob:pub uiFont: str = "Figtree, system-ui, sans-serif", ui: UiColors = UiColors();
glob:pub formStack: dict[str, str | int | float] = {
    "display": "flex", "flexDirection": "column", "gap": 16, "minWidth": 0,
    "color": ui.ink, "fontFamily": uiFont
};
glob:pub formInput: dict[str, str | int | float] = {
    "width": "100%", "minWidth": 0, "boxSizing": "border-box", "minHeight": 52,
    "padding": "13px 14px", "fontFamily": uiFont, "fontSize": 16,
    "border": "1px solid " + ui.line, "borderRadius": 12,
    "background": ui.white, "color": ui.ink
};
glob:pub formButton: dict[str, str | int | float] = {
    **formInput, "minHeight": 54, "background": ui.navy, "color": ui.accentText,
    "fontWeight": 800, "cursor": "pointer", "borderColor": ui.navy, "borderRadius": 14
};
glob:pub formSecondary: dict[str, str | int | float] = {
    **formButton, "background": ui.white, "color": ui.navy, "borderColor": ui.line
};
glob:pub formHint: dict[str, str | int | float] = {
    "fontSize": 13, "lineHeight": 1.5, "margin": 0, "color": ui.muted
};

# The browser-only store is shared by all controls; it owns subscription cleanup.
# Its dynamic JS interface is narrowed to ThemeSnapshot as it enters Jac.
glob browserGlobals: any = globalThis, themeStore: any = createThemeStore(browserGlobals.window);

def:pub useTheme() -> ThemeSnapshot {
    return useSyncExternalStore(themeStore.subscribe, themeStore.getSnapshot, themeStore.getSnapshot) as ThemeSnapshot;
}

def:pub ThemeControl() -> JsxElement {
    current = useTheme();
    nextMode = "light" if current.resolved == "dark" else "dark";
    label = "Switch to " + nextMode + " mode";
    return <button type="button" data-testid="theme-toggle" aria-label={label} title={label}
        onClick={lambda { themeStore.setPreference(nextMode); }}
        style={{"display": "inline-flex", "alignItems": "center", "justifyContent": "center", "width": 44, "height": 44, "flexShrink": 0, "padding": 0, "border": "1px solid " + ui.line, "borderRadius": 999, "background": ui.white, "color": ui.ink, "cursor": "pointer"}}>
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            {<Fragment><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.93 4.93l1.42 1.42M17.65 17.65l1.42 1.42M4.93 19.07l1.42-1.42M17.65 6.35l1.42-1.42"/></Fragment> if nextMode == "light" else <path d="M20.9 13A9 9 0 0 1 11 3.1 9 9 0 1 0 20.9 13Z"/>}
        </svg>
    </button>;
}

def:pub BrandLogo(reversed: bool = False) -> JsxElement {
    # One transparent silhouette keeps both themes optically identical.
    return <span role="img" aria-label="M Local" className="ml-brand" style={{"--ml-logo-ink": "#F9F6F0"} if reversed else {}}>
        <span aria-hidden="true" className="ml-brand-ink"/><span aria-hidden="true" className="ml-brand-square"/>
    </span>;
}

glob foundationStyles: str = """
@font-face{font-family:Figtree;src:url('/static/assets/brand/Figtree.ttf') format('truetype');font-style:normal;font-weight:300 900;font-display:swap}
:root{--ml-bg:#F9F6F0;--ml-surface:#FFFFFF;--ml-sunken:#EFE9DE;--ml-border:#DDD5C7;--ml-ink:#0B1F38;--ml-text:#3A4657;--ml-muted:#5F6B7A;--ml-accent:#02305C;--ml-accent-soft:#E3ECF7;--ml-accent-text:#FFFFFF;--ml-maize:#FEC809;--ml-good:#1E6B3F;--ml-good-soft:#E4F2E8;--ml-warn:#7A4A00;--ml-warn-soft:#FFF1CF;--ml-bad:#B42318;--ml-bad-soft:#FDECEA;--ml-focus:#2365A0;--ml-hover:#02305C22;--ml-disabled:#687787;--ml-ticket:#02305C;--ml-ticket-text:#F9F6F0;--ml-shadow:#001D3D18;--ml-chart-cancelled:#AF633C;--ml-chart-expired:#84745A}
:root[data-theme=dark]{--ml-bg:#091624;--ml-surface:#12243A;--ml-sunken:#1C3047;--ml-border:#34485F;--ml-ink:#F9F6F0;--ml-text:#D6DFE9;--ml-muted:#B0C0D1;--ml-accent:#FEC809;--ml-accent-soft:#323220;--ml-accent-text:#0B1F38;--ml-good:#91D6A7;--ml-good-soft:#153B2E;--ml-warn:#F5D58B;--ml-warn-soft:#3A3020;--ml-bad:#FFB4AA;--ml-bad-soft:#482A30;--ml-focus:#FEC809;--ml-hover:#FEC80944;--ml-disabled:#60748B;--ml-ticket:#17365A;--ml-ticket-text:#F9F6F0;--ml-shadow:#00000044;--ml-chart-cancelled:#E7A882;--ml-chart-expired:#B6A98F}
:root{--ml-logo-ink:#02305C;--ml-on-accent-mark:#FEC809;--ml-on-maize:#0B1F38;--ml-camera-bg:#0E1622;--ml-camera-ink:#F9F6F0;--ml-camera-muted:#C9D4E2;--ml-theme-time:220ms;--ml-theme-ease:cubic-bezier(.22,.61,.36,1)}
:root[data-theme=dark]{--ml-logo-ink:#F9F6F0;--ml-on-accent-mark:#02305C}
html,body,#root{background:var(--ml-bg);color:var(--ml-ink);font-family:Figtree,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
html,body,#root,#root *,#root *:before,#root *:after{transition:background-color var(--ml-theme-time) var(--ml-theme-ease),color var(--ml-theme-time) var(--ml-theme-ease),border-color var(--ml-theme-time) var(--ml-theme-ease),fill var(--ml-theme-time) var(--ml-theme-ease),stroke var(--ml-theme-time) var(--ml-theme-ease)}
.ml-brand{position:relative;display:block;width:112px;height:40px;flex-shrink:0}
.ml-brand-ink,.ml-brand-square{position:absolute;inset:0;-webkit-mask:url('/static/assets/brand/logo-master.png') center/contain no-repeat;mask:url('/static/assets/brand/logo-master.png') center/contain no-repeat}
.ml-brand-ink{background:var(--ml-logo-ink);clip-path:polygon(0 0,30% 0,30% 32%,42% 32%,42% 0,100% 0,100% 100%,0 100%)}
.ml-brand-square{background:var(--ml-maize);clip-path:inset(0 58% 68% 30%)}
#root input,#root textarea,#root select,#root button{font-family:Figtree,system-ui,sans-serif}
#root button,#root [role=button],#root input,#root select,#root textarea{transition:background-color var(--ml-theme-time) var(--ml-theme-ease),color var(--ml-theme-time) var(--ml-theme-ease),border-color var(--ml-theme-time) var(--ml-theme-ease),box-shadow 150ms ease,transform 150ms ease}
#root button,#root [role=button]{min-height:44px}
#root button:not(:disabled):hover,#root [role=button]:not([aria-disabled=true]):hover{box-shadow:inset 0 0 0 1px var(--ml-hover)}
#root button:focus-visible,#root [role=button]:focus-visible,#root input:focus-visible,#root select:focus-visible,#root textarea:focus-visible,#root summary:focus-visible{outline:3px solid var(--ml-focus);outline-offset:3px}
#root summary{padding:12px 0;min-height:44px;box-sizing:border-box;cursor:pointer;font-weight:700;color:var(--ml-accent)}
#root details[open]>summary{margin-bottom:12px}
#root button:disabled,#root [aria-disabled=true]{opacity:.55;cursor:default}
#root input[type=checkbox]{accent-color:var(--ml-accent)}
#root a{color:var(--ml-accent);text-underline-offset:3px}
[data-testid=app-tabbar]{padding-bottom:max(4px,env(safe-area-inset-bottom))!important}
[data-testid=app-masthead]{padding-top:max(16px,env(safe-area-inset-top))!important}
.ml-welcome-choice{position:relative}
.ml-welcome-choice:first-child:after{content:'';position:absolute;right:22px;top:-7px;width:18px;height:18px;border-radius:3px;background:var(--ml-on-accent-mark)}
.ml-welcome-choice:active{transform:translateY(1px)}
.ml-qr-ticket{position:relative;border:1px solid var(--ml-border);box-shadow:0 8px 24px var(--ml-shadow)}
.ml-qr-ticket:before{content:'';position:absolute;right:18px;top:-9px;width:20px;height:20px;border-radius:3px;background:var(--ml-maize)}
.ml-scan-window{position:relative;min-height:240px;border-radius:20px;background:var(--ml-camera-bg);overflow:hidden;display:flex;align-items:center;justify-content:center}
.ml-scan-reticle{position:absolute;inset:30px;pointer-events:none;background:linear-gradient(var(--ml-maize),var(--ml-maize)) left top/36px 4px no-repeat,linear-gradient(var(--ml-maize),var(--ml-maize)) left top/4px 36px no-repeat,linear-gradient(var(--ml-maize),var(--ml-maize)) right top/36px 4px no-repeat,linear-gradient(var(--ml-maize),var(--ml-maize)) right top/4px 36px no-repeat,linear-gradient(var(--ml-maize),var(--ml-maize)) left bottom/36px 4px no-repeat,linear-gradient(var(--ml-maize),var(--ml-maize)) left bottom/4px 36px no-repeat,linear-gradient(var(--ml-maize),var(--ml-maize)) right bottom/36px 4px no-repeat,linear-gradient(var(--ml-maize),var(--ml-maize)) right bottom/4px 36px no-repeat}
@media(prefers-reduced-motion:reduce){html,body,#root,#root *,#root *:before,#root *:after{transition:none!important;animation:none!important}
}
""";

def:pub UiFoundation() -> JsxElement {
    current = useTheme();
    useLayoutEffect(lambda {
        document.documentElement.dataset["theme"] = current.resolved;
        document.documentElement.style.setProperty("color-scheme", current.resolved);
    }, [current.resolved]);
    return <Fragment><DocumentHead /><style>{foundationStyles}</style><AppOpener /></Fragment>;
}

def:pub NavIcon(name: str, active: bool = False) -> JsxElement {
    paths: dict[str, JsxElement] = {
        "discover": <Fragment><path d="M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/></Fragment>,
        "merchant": <Fragment><rect x="4" y="7" width="16" height="14" rx="2"/><path d="M8 7V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v3M8 12h8M8 16h5"/></Fragment>,
        "redeem": <Fragment><path d="M3 8V3h5M16 3h5v5M21 16v5h-5M8 21H3v-5M7 7h3v3H7zM14 7h3v3h-3zM7 14h3v3H7zM14 14h3v3h-3z"/></Fragment>,
        "insights": <Fragment><path d="M4 3v18h17M8 16v-5M13 16V6M18 16v-8"/></Fragment>,
        "account": <Fragment><circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/></Fragment>
    };
    return <svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke={ui.navy if active else ui.muted} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

def:pub StockBar(remaining: int, total: int) -> JsxElement {
    if not (total > 0) { return <Fragment/>; }
    width: float = remaining / total * 100;
    if width < 0 { width = 0.0; }
    elif width > 100 { width = 100.0; }
    return <div aria-hidden="true" style={{"height": 4, "borderRadius": 3, "background": ui.inset, "overflow": "hidden", "width": "100%"}}><div style={{"height": "100%", "width": str(width) + "%", "borderRadius": 3, "background": ui.navy}}/></div>;
}
