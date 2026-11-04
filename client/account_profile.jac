"""Editable account name; email and access remain owned by sign-in services."""
import from "react" { useEffect }
import from .ui { formStack, formInput, formSecondary, formHint }
import from .legal { LegalLinks }
import type from ..services.account_profile { AccountProfileView }

glob stack = formStack, inputStyle = formInput, button = formSecondary, hint = formHint;

def:pub AccountProfile(
    getProfile: Callable[[], AccountProfileView],
    saveProfile: Callable[[str], AccountProfileView],
    onSaved: Callable[[str], None]
) -> JsxElement {
    has profile: AccountProfileView | None = None,
        name: str = "", busy: bool = False, loading: bool = True,
        message: str = "", failed: bool = False,
        mounted: Ref[bool] = Ref(False), inFlight: Ref[bool] = Ref(False);

    async def load {
        if inFlight.current { return; }
        inFlight.current = True;
        loading = True;
        message = "";
        failed = False;
        try {
            reply = await getProfile();
            if not mounted.current { return; }
            if not reply.ok {
                failed = True;
                message = reply.message or "Could not load your account.";
                return;
            }
            profile = reply;
            name = reply.display_name or "";
        } except Exception {
            if mounted.current {
                failed = True;
                message = "Could not load your account. Check your connection and retry.";
            }
        } finally {
            inFlight.current = False;
            if mounted.current { loading = False; }
        }
    }

    useEffect(lambda {
        mounted.current = True;
        load();
        return lambda { mounted.current = False; };
    }, []);

    async def save(event: FormEvent) {
        event.preventDefault();
        if inFlight.current { return; }
        clean = name.strip();
        if not clean or len(clean) > 80 {
            failed = True;
            message = "Enter a display name between 1 and 80 characters.";
            return;
        }
        inFlight.current = True;
        busy = True;
        failed = False;
        message = "";
        try {
            reply = await saveProfile(clean);
            if not mounted.current { return; }
            if not reply.ok {
                failed = True;
                message = reply.message or "Your account could not be saved.";
                return;
            }
            profile = reply;
            name = reply.display_name;
            message = reply.message or "Account profile saved.";
            await onSaved(reply.display_name);
        } except Exception {
            if mounted.current {
                failed = True;
                message = "Could not save your account. Your entries are kept; check the connection and retry.";
            }
        } finally {
            inFlight.current = False;
            if mounted.current { busy = False; }
        }
    }

    def cancelChanges {
        if profile { name = profile.display_name or ""; }
        message = "";
        failed = False;
    }

    return <section aria-label="Account profile" style={{**stack, "paddingTop": 16, "borderTop": "1px solid var(--ml-border)"}}>
        <h3 style={{"fontSize": 20, "margin": 0}}>Account profile</h3>
        {(<p role="status" style={hint}>Loading your account...</p>) if loading else (
            <form style={stack} onSubmit={save} noValidate={True}>
                <label style={{**stack, "gap": 6, "fontSize": 14, "fontWeight": 600}}>
                    Display name<input style={inputStyle} placeholder="Display name" autoComplete="name" value={name} maxLength={80} required={True} disabled={busy} onChange={lambda (e: ChangeEvent) { name = e.target.value; }} />
                </label>
                <div style={stack}>
                    <div><strong style={{"fontSize": 14}}>Email</strong><p style={{**hint, "overflowWrap": "anywhere"}}>{profile.email or "Not available for this account"}</p></div>
                    <p style={hint}>{"Email verified" if profile.email_verified else "Email not verified"}</p>
                    <p style={hint}>{"Business owner" if profile.role == "merchant" else "Business account · finish your profile to start posting" if profile.role == "business" else "U-M customer account" if profile.role == "student" else "Account access"}<br/>Your email and account access are managed by the sign-in service.</p>
                </div>
                <div style={{"display": "flex", "gap": 8, "flexWrap": "wrap"}}>
                    <button style={{**button, "flex": "1 1 160px", "background": "var(--ml-accent)", "borderColor": "var(--ml-accent)", "color": "var(--ml-accent-text)"}} disabled={busy or name.strip() == (profile.display_name or "")}>{"Saving account..." if busy else "Save account"}</button>
                    <button style={{**button, "flex": "1 1 160px"}} type="button" disabled={busy} onClick={cancelChanges}>Cancel changes</button>
                </div>
            </form>
        ) if profile else <button style={button} type="button" onClick={load}>Retry account</button>}
        {(<p role={"alert" if failed else "status"} aria-live="polite" style={{**hint, "color": "var(--ml-bad)" if failed else "var(--ml-accent)"}}>{message}</p>) if message else None}
        <p style={hint}><LegalLinks /> · Delete your account or get a copy of your data by emailing the address in the Privacy Policy.</p>
    </section>;
}
