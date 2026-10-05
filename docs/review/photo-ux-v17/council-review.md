# Council verdict — M-Local former design, simpler navigation and connected photo revision

_4 members · Custom product/design/media panel council · 2026-10-05 19:25_

## Synthesis

### Summary
Keep the navigation improvements; accept that the prior visual pass was incomplete. Complete and verify the connected image workflow.

### Consensus
- Separate business and offer imagery.
- Use phone uploads and visible website thumbnails as primary controls.
- Retain navy, maize, Figtree, prices, statuses and saved QR clarity.
- Keep operational merchant screens compact.

### Prioritized Actions
-
  - **Action:** Canonical copies of website photos, normalized like phone uploads
  - **Status:** Verified in the isolated local proposal; see final evidence scope below
-
  - **Action:** Random public filenames and private ownership/deduplication records
  - **Status:** Verified in the isolated local proposal; see final evidence scope below
-
  - **Action:** Upload/choose → save → reopen → displayed business and offer pages
  - **Status:** Verified in the isolated local proposal; see final evidence scope below
-
  - **Action:** Populated mobile views and theme/failure cases
  - **Status:** Verified in the isolated local proposal; see final evidence scope below
-
  - **Action:** Durable mount, backup and conservative orphan cleanup
  - **Status:** Production acceptance remains open

### Disagreements
- The missing offer-image fallback finding was stale: the revised component handles errors.
- The server sees a resized image, so its pixel cap does not directly reject the large original. Phone decoding memory remains a valid device-test concern.

### Scope
Four independent native-agent reviews, followed by an additional chair synthesis pass by the design advisor; simulated expert/persona lenses, not actual customer research. Named Workflow runner was unavailable, so this is the disclosed native-agent fallback. Grades apply to reviewed UX/media scope, not launch readiness.

## Member verdicts

### Simulated U-M student
- **Grade:** Former B− → simplification B
- **Recommendation:** Keep the simpler shell. Separate item photos from business identity, then judge a populated feed.
- **Evidence:**
  - main.jac:156 unchanged 96px business image before this revision
  - services/promo.jac:446 projected the same restaurant image onto every offer
  - Current student screenshot was empty; former was a populated saved-claim state.
- **Keep:**
  - Local offers
  - Favorites only when present
  - One theme control
  - Direct saved-QR access

### Simulated Ann Arbor business operator
- **Grade:** Former B− → simplification B
- **Recommendation:** Offers-first and Scan QR match daily work. Compact the header, collapse past offers and make photos usable from a phone.
- **Evidence:**
  - Former routing landed merchants on Insights
  - Current operational header and two large utility controls delayed New offer
  - Offer editor had no offer-specific image authoring
  - Ended paused offers still showed Resume.

### Independent design advisor and skeptic
- **Grade:** B navigation; C+ modern visual execution before the image revision
- **Recommendation:** Retain Michigan identity and the simpler navigation. Build one coherent photo workflow across discovery, detail, business profile and authoring.
- **Evidence:**
  - Figtree, navy/maize and the former business hero already provided strong identity
  - Old and new screenshots used different content states, limiting comparison
  - Large repeated business images would not identify different offers.
- **Questions:**
  - Browse-before-verification is a separate acquisition decision; no change made.
  - Separate logo and cover fields are optional future refinement.

### Simulated media, trust and accessibility expert
- **Grade:** B− phone uploads; C website trust; C+ media readiness before final fixes
- **Recommendation:** Normalize selected website photos, remove owner-derived public names, verify persistence and keep upload ownership private.
- **Evidence:**
  - Jac0.37.23 serves project assets through /static/{file_path:path}
  - First image proposal normalized uploads but stored remote website hotlinks
  - First public filenames used a stable hashed owner prefix
- **Risks:**
  - Persistent photo volume and private ownership database must be backed up together.
  - Orphan cleanup needs an inventory of references and a grace period.
  - Physical iPhone decoding/memory behavior remains unverified.

## My candid read

I defend Offers-first and Scan QR because they put daily work within reach, and retain Michigan navy/maize and Figtree. I accept the image criticism: navigation and headings alone were an incomplete visual pass. I adopted phone uploads, visible website thumbnail choices, separate offer photos, canonical normalized copies, random public names, private ownership records, failed-image handling and collapsed offer history. The local setup/edit/display journeys now pass, including actual browser file uploads, save/reopen, public display and native persistence restart. Browser review caught a real ingress gap; exact photo routes, protected photo RPCs and a bounded upload body now pass regression checks. A populated comparison uses the same fictional account/backend/offer data: the former feed repeats a business photo while the revision identifies individual offers. Production storage/backup, orphan lifecycle, physical Safari/HEIC, real-business website checks and the separate derivative-runtime release blocker remain open. I deferred additional logo/cover/gallery fields and object-storage infrastructure until a real requirement demands them.
