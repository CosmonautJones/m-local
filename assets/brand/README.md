`logo-compact.png`, `logo-reversed.png`, and `app-icon.png` are copied unchanged from the user-supplied Mobile app screens and flows v2 archive.

`logo-master.png` is a transparent silhouette recreated with the built-in image
generator from the compact reference on 2026-09-27. Both app themes use this one
master through a CSS alpha mask: navy/cream lettering and a maize destination
square, with identical geometry and no baked-in background. The detached square
occupies x=30–42%, y=0–32% of the canvas; the two complementary CSS clips in
`client/ui.jac` color it separately. Preserve that alignment when replacing the
master. The original PNGs remain available as source references.

Final generation prompt (built-in image generation, transparent background):

> Recreate this simple logo as pristine digital vector-style artwork on transparent alpha. Use the input only as a design reference. Draw NEW CLEAN FILLED SHAPES, not a distressed cutout or threshold of the input. Make the full M Local wordmark solid black, including the small detached square above the M. Wide 2.8:1 lockup: stylized geometric M cut by an upward diagonal empty stripe, followed directly by bold rounded 'Local' lettering. There is exactly one M (the icon), no extra M in the text. The square is detached above the upper right corner of the M. Preserve the reference composition and recognizable silhouette. Very smooth continuous outer and inner edges, generous clean transparent counters inside o and a, absolutely NO speckles, texture, scratches, grain, glow, ghosting, gradients, outlines or shadows. Uniform 100% opaque black everywhere inside each shape; transparent everywhere outside. Keep a small transparent margin so no shapes touch the canvas edges. This is a professional reusable alpha mask for CSS, so the entire background and all letter holes must be truly transparent. Deliver just one immaculate black logo, not a presentation board.

Figtree is a variable font from the Google Fonts Figtree distribution, licensed under the included SIL Open Font License (OFL.txt).
The font and images are served locally by Jac; no third-party font request is required.

`m-mark-maize.png` and `local-word-white.png` are cut from `logo-compact.png` (M at 0,36 150x124; Local at 170,36 280x124) and recolored for the navy app opener in `client/app-opener.jsx`, matching the Claude Design "Mmm Local Intro".
