"""PromoPusher design tokens and stylesheet factory (React Native StyleSheet).

No JSX here: E1105 is only enforced on main.jac, so UI stays there.
"""

import from "@jac/mobui" { StyleSheet }


glob:pub C: dict[str, str] = {
         "bg": "var(--ml-bg)",
         "surface": "var(--ml-surface)",
         "sunken": "var(--ml-sunken)",
         "border": "var(--ml-border)",
         "ink": "var(--ml-ink)",
         "text": "var(--ml-text)",
         "muted": "var(--ml-muted)",
         "accent": "var(--ml-accent)",
         "accentSoft": "var(--ml-accent-soft)",
         "accentText": "var(--ml-accent-text)",
         "brand": "var(--ml-accent)",
         "good": "var(--ml-good)",
         "goodSoft": "var(--ml-good-soft)",
         "warn": "var(--ml-warn)",
         "warnSoft": "var(--ml-warn-soft)",
         "bad": "var(--ml-bad)",
         "badSoft": "var(--ml-bad-soft)"
     },
     S: dict[str, int] = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 20, "xxl": 28},
     R: dict[str, int] = {"sm": 8, "md": 12, "lg": 18, "pill": 999},
     F: dict[str, int] = {"xs": 12, "sm": 13, "md": 15, "lg": 18, "xl": 24, "xxl": 30};


def:pub buildStyles(T: dict[str, str]) -> any {
    return StyleSheet.create(
        {
            "hidden": {"display": "none"},
            "screen": {"flex": 1, "backgroundColor": T["bg"]},
            "frame": {
                "flex": 1,
                "width": "100%",
                "maxWidth": 520,
                "alignSelf": "center",
                "backgroundColor": T["bg"]
            },
            "scroll": {"flex": 1},
            "content": {
                "paddingHorizontal": S["xl"],
                "paddingTop": S["xl"],
                "paddingBottom": 92,
                "gap": S["lg"]
            },
            "header": {"gap": 8},
            "brandRow": {
                "flexDirection": "row",
                "alignItems": "center",
                "justifyContent": "space-between"
            },
            "brand": {
                "fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["md"],
                "fontWeight": "800",
                "color": T["accent"],
                "letterSpacing": 0.5
            },
            "title": {
                "fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["xxl"],
                "fontWeight": "800",
                "color": T["ink"],
                "lineHeight": 34, "letterSpacing": -0.7
            },
            "h2": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["lg"], "fontWeight": "800", "color": T["ink"]},
            "subtitle": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["md"], "color": T["muted"], "lineHeight": 21},
            "body": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["md"], "color": T["text"], "lineHeight": 22},
            "small": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["sm"], "color": T["muted"], "lineHeight": 19},
            "label": {
                "fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["sm"],
                "fontWeight": "700",
                "color": T["muted"],
            },
            "row": {"flexDirection": "row", "alignItems": "center", "gap": S["sm"]},
            "rowBetween": {
                "flexDirection": "row",
                "alignItems": "center",
                "justifyContent": "space-between",
                "gap": S["sm"]
            },
            "wrap": {"flexDirection": "row", "flexWrap": "wrap", "gap": S["sm"]},
            "card": {
                "backgroundColor": T["surface"],
                "borderRadius": R["lg"],
                "borderWidth": 1,
                "borderColor": T["border"],
                "padding": S["lg"],
                "gap": S["sm"]
            },
            "cardMuted": {"opacity": 0.6},
            "section": {
                "backgroundColor": T["surface"],
                "borderRadius": R["lg"],
                "borderWidth": 1,
                "borderColor": T["border"],
                "padding": S["lg"],
                "gap": S["md"]
            },
            "restaurant": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["sm"], "fontWeight": "700", "color": T["brand"]},
            "offerTitle": {
                "fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["lg"],
                "fontWeight": "800",
                "color": T["ink"],
                "lineHeight": 24
            },
            "price": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["xl"], "fontWeight": "800", "color": T["ink"]},
            "priceBig": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": 40, "fontWeight": "800", "color": T["ink"]},
            "strike": {
                "fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["md"],
                "color": T["muted"],
                "textDecorationLine": "line-through"
            },
            "save": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["sm"], "fontWeight": "800", "color": T["good"]},
            "chip": {
                "minHeight": 44, "justifyContent": "center",
                "paddingVertical": 10,
                "paddingHorizontal": S["md"],
                "borderRadius": R["pill"],
                "borderWidth": 1,
                "borderColor": T["border"],
                "backgroundColor": T["surface"]
            },
            "chipOn": {"backgroundColor": T["brand"], "borderColor": T["brand"]},
            "chipText": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["sm"], "fontWeight": "600", "color": T["text"]},
            "chipTextOn": {"color": T["accentText"]},
            "tag": {
                "paddingVertical": 3,
                "paddingHorizontal": S["sm"],
                "borderRadius": R["pill"],
                "backgroundColor": T["sunken"]
            },
            "tagText": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["xs"], "fontWeight": "700", "color": T["text"]},
            "badge": {
                "paddingVertical": 3,
                "paddingHorizontal": S["sm"],
                "borderRadius": R["pill"],
                "backgroundColor": T["goodSoft"]
            },
            "badgeText": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["xs"], "fontWeight": "800", "color": T["good"]},
            "note": {
                "backgroundColor": T["warnSoft"],
                "borderRadius": R["md"],
                "padding": S["md"],
                "gap": S["xs"]
            },
            "noteText": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["sm"], "color": T["warn"], "lineHeight": 19},
            "input": {
                "minHeight": 52,
                "paddingVertical": S["md"],
                "paddingHorizontal": S["md"],
                "borderRadius": R["md"],
                "borderWidth": 1,
                "borderColor": T["border"],
                "backgroundColor": T["surface"],
                "color": T["ink"],
                "fontFamily": "Figtree, system-ui, sans-serif", "fontSize": 16
            },
            "inputMulti": {"minHeight": 72, "textAlignVertical": "top"},
            "field": {"gap": 6, "flexShrink": 0},
            "fieldRow": {"flexDirection": "row", "gap": S["md"]},
            "flex1": {"flex": 1},
            "btn": {
                "minHeight": 54, "justifyContent": "center",
                "paddingVertical": 14,
                "paddingHorizontal": S["lg"],
                "borderRadius": R["md"],
                "backgroundColor": T["accent"],
                "alignItems": "center"
            },
            "btnText": {"color": T["accentText"], "fontWeight": "800", "fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["md"]},
            "btnGhost": {
                "minHeight": 44, "justifyContent": "center",
                "paddingVertical": 10,
                "paddingHorizontal": S["md"],
                "borderRadius": R["md"],
                "borderWidth": 1,
                "borderColor": T["border"],
                "backgroundColor": T["surface"],
                "alignItems": "center"
            },
            "btnGhostText": {"color": T["ink"], "fontWeight": "700", "fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["sm"]},
            "btnDisabled": {"backgroundColor": "var(--ml-disabled)"},
            "link": {"color": T["accent"], "fontWeight": "700", "fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["md"]},
            "msgGood": {
                "backgroundColor": T["goodSoft"],
                "borderRadius": R["md"],
                "padding": S["md"]
            },
            "msgGoodText": {"color": T["good"], "fontWeight": "700", "fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["md"]},
            "msgBad": {
                "backgroundColor": T["badSoft"],
                "borderRadius": R["md"],
                "padding": S["md"]
            },
            "msgBadText": {"color": T["bad"], "fontWeight": "700", "fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["md"]},
            "reason": {"flexDirection": "row", "gap": S["sm"], "alignItems": "flex-start"},
            "dot": {
                "width": 8,
                "height": 8,
                "borderRadius": 4,
                "marginTop": 7,
                "backgroundColor": T["accent"]
            },
            "empty": {
                "padding": S["xxl"],
                "alignItems": "center",
                "gap": S["sm"],
                "backgroundColor": T["surface"],
                "borderRadius": R["lg"],
                "borderWidth": 1,
                "borderColor": T["border"]
            },
            "tabbar": {
                "position": "absolute",
                "left": 0,
                "right": 0,
                "bottom": 0,
                "flexDirection": "row",
                "backgroundColor": T["surface"],
                "borderTopWidth": 1,
                "borderTopColor": T["border"],
                "paddingVertical": 4,
                "paddingHorizontal": S["sm"]
            },
            "tab": {
                "borderTopWidth": 3, "borderTopColor": "transparent", "minHeight": 52,
                "flex": 1,
                "alignItems": "center",
                "paddingVertical": 4,
                "borderRadius": 0,
                "gap": 2
            },
            "tabOn": {"backgroundColor": T["surface"], "borderTopColor": "var(--ml-maize)"},
            "tabText": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["sm"], "fontWeight": "700", "color": T["muted"]},
            "tabTextOn": {"color": T["accent"]},
            "status": {
                "paddingVertical": 3,
                "paddingHorizontal": S["sm"],
                "borderRadius": R["pill"]
            },
            "statusText": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": F["xs"], "fontWeight": "800"},
            "masthead": {"paddingHorizontal": 20, "paddingTop": 16, "paddingBottom": 4, "flexDirection": "row", "flexWrap": "wrap", "alignItems": "center", "justifyContent": "space-between", "gap": 12},
            "headerActions": {"flexDirection": "row", "flexWrap": "wrap", "alignItems": "center", "gap": S["sm"], "minWidth": 0, "maxWidth": "100%", "flexShrink": 1},
            "sessionPanel": {"marginHorizontal": 20, "marginTop": 12, "padding": 16, "gap": 12, "borderRadius": 18, "backgroundColor": T["surface"], "borderWidth": 1, "borderColor": T["border"]},
            "filterPanel": {"padding": 14, "gap": 12, "backgroundColor": T["surface"], "borderRadius": 16, "borderWidth": 1, "borderColor": T["border"]},
            "claimPass": {"backgroundColor": "var(--ml-ticket)", "padding": 20, "borderRadius": 24, "gap": 14},
            "claimHeading": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": 22, "fontWeight": "800", "color": "var(--ml-ticket-text)", "letterSpacing": -0.3},
            "claimBody": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": 15, "color": "var(--ml-ticket-text)", "lineHeight": 22},
            "claimLabel": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": 12, "fontWeight": "800", "color": "var(--ml-maize)", "letterSpacing": 0.7},
            "claimPrice": {"fontFamily": "Figtree, system-ui, sans-serif", "fontSize": 32, "fontWeight": "800", "color": "var(--ml-ticket-text)"},
            "divider": {"height": 1, "backgroundColor": T["border"]}
        }
    );
}


"""Background / text colors for an offer or claim status pill."""
def:pub statusColors(state: str) -> list[str] {
    if state in ["active", "claimed"] {
        return [C["goodSoft"], C["good"]];
    }
    if state in ["scheduled", "paused"] {
        return [C["warnSoft"], C["warn"]];
    }
    if state == "redeemed" {
        return [C["accentSoft"], C["brand"]];
    }
    return [C["badSoft"], C["bad"]];
}


def:pub money(v: float) -> str {
    cents: int = int(round(v * 100));
    whole = cents // 100;
    rest = cents % 100;
    pad = "0" if rest < 10 else "";
    return "$" + str(whole) + "." + pad + str(rest);
}
