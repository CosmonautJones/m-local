"""Privacy Policy and Terms of Use, shown at /#privacy and /#terms.

The text describes what this build actually collects and who receives it. Keep
it in step with the code: if a change adds data, a recipient or a retention
period, update the matching section and LEGAL_UPDATED in the same commit.
"""
import from .ui { formStack, formSecondary, formHint, uiFont }

glob:pub LEGAL_UPDATED: str = "November 3, 2026",
     LEGAL_OPERATOR: str = "Travis Jones",
     LEGAL_CONTACT: str = "mlocal.approvals@gmail.com";

glob PRIVACY: list[list[str]] = [
    ["Who we are",
     "M-Local is a small service that shows time-limited deals from Ann Arbor businesses to the University of Michigan community. It is operated by " + LEGAL_OPERATOR + " in Ann Arbor, Michigan (\"we\"). M-Local is independent and is not affiliated with or endorsed by the University of Michigan.",
     "Questions or requests about your information: " + LEGAL_CONTACT + "."],
    ["What we collect from students",
     "Your @umich.edu email address and the name you enter. We use the email only to send sign-in codes and important account notices.",
     "The deals you claim, cancel and redeem, with their times, and the one-time QR code for each claim.",
     "The tastes and favorite places you choose to save. They only change the order of deals shown to you.",
     "We never ask for your university password, and we do not collect payment details: you pay the business directly."],
    ["What we collect from businesses",
     "Your work email and name, and the business profile you submit: name, address, cuisine, description, website, menu details and photos.",
     "Our review of your submission (who approved it, when and a short note), and the offers you publish and redeem.",
     "If you use website import, we read the public web page you give us to suggest profile details and photos."],
    ["Information collected automatically",
     "Our hosting provider records technical request information such as IP address, browser type and time, used to run and secure the service.",
     "Your browser stores your sign-in session, your chosen view and theme, and unfinished offer drafts on your own device. We do not use advertising or analytics cookies, and we do not load third-party trackers."],
    ["How we use information",
     "To run M-Local: sign you in, show and order deals, hold and redeem claims, prevent a QR code being used twice, enforce the two-hold limit, review businesses and keep the service secure.",
     "Businesses see totals about their own offers (for example how many were claimed or redeemed). When a business scans your QR code it sees the offer and its terms, not your name or email.",
     "We do not sell or rent your information, and we do not use it for advertising."],
    ["Who we share it with",
     "Service providers that run M-Local for us: JacHammer (application hosting and database, on Amazon Web Services in the United States) and Resend (sending sign-in and notice emails). They process information only to provide their service to us.",
     "Authorities or others when the law requires it, or to protect the safety of people or the service.",
     "If M-Local is transferred to someone who continues the service, this policy continues to apply to your information."],
    ["How long we keep it",
     "Sign-in codes expire after 10 minutes. Records of sign-in emails sent are deleted after 24 hours.",
     "Your account, claims, tastes and favorites are kept while your account exists, so your saved passes and history keep working.",
     "Encrypted backups are kept for 14 days and then deleted.",
     "When you ask us to delete your account we delete or anonymize your information within 30 days, except where we must keep a record of a redeemed claim to resolve a dispute with a business, which we keep no longer than 12 months."],
    ["Your choices",
     "You can change your display name in your account and log out at any time. Sessions end automatically after 30 days.",
     "Email " + LEGAL_CONTACT + " from the address on your account to get a copy of your information, correct it, or delete your account. We answer within 30 days."],
    ["Security",
     "Connections are encrypted, sign-in codes are stored only as one-way hashes, and backups are encrypted. No service is perfectly secure; tell us right away at " + LEGAL_CONTACT + " if you think your account was misused."],
    ["Children",
     "M-Local is meant for members of the U-M community and is not directed to children under 13. We do not knowingly collect information from children under 13; if you believe we have, contact us and we will delete it."],
    ["Changes to this policy",
     "We will post any change here with a new date, and tell signed-up users by email or in the app before a significant change takes effect."]
];

glob TERMS: list[list[str]] = [
    ["Agreement",
     "These terms are an agreement between you and " + LEGAL_OPERATOR + ", who operates M-Local (\"we\"). By creating an account or signing in, you agree to these terms and acknowledge the Privacy Policy. If you do not agree, do not use M-Local."],
    ["Who can use M-Local",
     "Students and other people with an @umich.edu email address can claim deals. Businesses can apply to list deals. You must be at least 13, and if you are under 18 you need a parent or guardian's permission. Signing in with a U-M address does not mean the University of Michigan endorses M-Local or confirms your enrollment.",
     "Keep your email account secure; anyone who can read it can sign in as you. One account per person."],
    ["How deals work",
     "Deals are offered by the businesses, not by us. The business sets the price, quantity, times and any conditions, and is responsible for honoring them. Payment happens directly between you and the business.",
     "Claiming a deal holds it for you for up to 20 minutes, or until the deal ends if sooner. You can hold at most two deals at a time. Each QR code works once. Show it at the business to redeem it.",
     "Deals can sell out, change or end. A business may refuse a claim that does not meet the deal's stated conditions. Sample deals marked \"Sample\" are for testing and are not real promotions."],
    ["Rules for everyone",
     "Do not copy, share, sell or alter QR codes, create accounts to get around limits, use another person's account, submit false information, disrupt or probe the service, scrape it, or use it to break the law or harm others.",
     "We may suspend or close accounts, hide listings or cancel holds that break these terms or put people or the service at risk."],
    ["Business terms",
     "If you list a business, you confirm you are authorized to represent it at the address you submit. We review the business name and address before a listing goes live and may refuse or remove any listing.",
     "You are responsible for your offers: they must be accurate, honored as published, and lawful, including any rules for age-restricted products, food safety, pricing and advertising. Do not offer alcohol, tobacco, cannabis or other age-restricted products through M-Local.",
     "You keep ownership of the content you submit (text, menus, photos, logos). You give us a non-exclusive, royalty-free license to host, display and adapt it to run and promote M-Local while it is listed. Only submit content you have the right to use.",
     "Listing and using M-Local is free during this launch period. We will give at least 30 days' notice before introducing any fee."],
    ["Your content and feedback",
     "Anything you submit must not infringe anyone's rights. If you send us suggestions, we may use them without obligation to you."],
    ["Availability and changes",
     "M-Local is offered as is and may change, pause or stop at any time. We may update these terms; we will post the new version with a new date and, for significant changes, tell signed-up users first. Continuing to use M-Local after a change means you accept it."],
    ["Disclaimers",
     "To the fullest extent the law allows, M-Local is provided without warranties of any kind, express or implied, including fitness for a particular purpose and non-infringement. We do not guarantee that any deal will be available or honored, or that the service will be uninterrupted or error-free. We are not responsible for the food, products or services of any business."],
    ["Limitation of liability",
     "To the fullest extent the law allows, we are not liable for indirect, incidental, special or consequential damages, or for lost profits or data, and our total liability for any claim about M-Local is limited to $50. Some places do not allow these limits, so they may not apply to you."],
    ["Disputes",
     "Please contact us first at " + LEGAL_CONTACT + " so we can try to resolve the issue. These terms are governed by the laws of the State of Michigan, and any dispute will be heard in the state or federal courts located in Washtenaw County, Michigan, unless the law requires otherwise."],
    ["Ending your use",
     "You can stop using M-Local at any time and ask us to delete your account as described in the Privacy Policy. Sections that by their nature should continue (such as content licenses, disclaimers and limits of liability) survive."],
    ["Contact",
     LEGAL_OPERATOR + ", Ann Arbor, Michigan. " + LEGAL_CONTACT + "."]
];


def:pub LegalLinks(newTab: bool = False) -> JsxElement {
    target = "_blank" if newTab else "_self";
    rel = "noopener" if newTab else "";
    return <span>
        <a href="/#terms" target={target} rel={rel} style={{"color": "inherit"}}>Terms</a>
        {" · "}
        <a href="/#privacy" target={target} rel={rel} style={{"color": "inherit"}}>Privacy Policy</a>
    </span>;
}


def:pub LegalPage(page: str, onBack: Callable[[], None]) -> JsxElement {
    privacy = page == "privacy";
    sections = PRIVACY if privacy else TERMS;
    return <main aria-label={"Privacy Policy" if privacy else "Terms of Use"} style={{**formStack, "boxSizing": "border-box", "maxWidth": 720, "margin": "0 auto", "padding": "28px 18px 48px", "fontFamily": uiFont, "color": "var(--ml-ink)", "gap": 18}}>
        <div style={{"display": "flex", "justifyContent": "space-between", "alignItems": "center", "gap": 12, "flexWrap": "wrap"}}>
            <button style={{**formSecondary, "width": "auto", "padding": "10px 16px"}} type="button" onClick={lambda { onBack(); }}>Back to M-Local</button>
            <a href={"/#terms" if privacy else "/#privacy"} style={{"color": "var(--ml-accent)", "fontWeight": 700}}>{"Terms of Use" if privacy else "Privacy Policy"}</a>
        </div>
        <header style={{**formStack, "gap": 6}}>
            <h1 style={{"fontSize": 32, "margin": 0}}>{"Privacy Policy" if privacy else "Terms of Use"}</h1>
            <p style={formHint}>{"Last updated " + LEGAL_UPDATED}</p>
        </header>
        {[<section key={str(i)} style={{**formStack, "gap": 8}}>
            <h2 style={{"fontSize": 20, "margin": "8px 0 0"}}>{s[0]}</h2>
            {[<p key={str(j)} style={{"margin": 0, "lineHeight": 1.6}}>{t}</p> for (j, t) in enumerate(s[1:])]}
        </section> for (i, s) in enumerate(sections)]}
    </main>;
}
