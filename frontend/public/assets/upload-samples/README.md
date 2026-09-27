# Passport upload samples

The personal-details and address-page illustrations previously shown in the
upload flow are preserved unchanged in:

`frontend/features/upload/components/passport-detail-samples-original.tsx`

The exported `OriginalPassportDetailSample` component accepts `page="front"`
for personal details or `page="back"` for address details. These originals were
retained at the user's explicit request; do not delete them when updating the
active samples.

To restore them, import `OriginalPassportDetailSample` into
`frontend/features/upload/components/passport-upload-page.tsx` and return
`<OriginalPassportDetailSample page={page} />` from `PassportPageSample` after
its front-cover/back-cover branch. That restores both original detail-page
illustrations without changing either cover sample.

The replacement Indian-passport-inspired illustrations use these assets:

- `indian-passport-personal-details.svg`
- `indian-passport-address-details.svg`

These are lightweight, editable SVG illustrations with fictional placeholders,
Hindi/English headings and visible SAMPLE / NOT VALID FOR TRAVEL markings.
They depict an identity page and a family/address page; they are visual upload
guides, not reproductions of valid documents. General field grouping follows the
[Indian Embassy's description of first and last passport pages](https://www.indianembassyoslo.gov.in/page/re-issue-of-passport/).

The separately supplied `passport-front-cover.png`, `passport-back-cover.png`,
and `visa-photo.png` assets are unchanged. Their source images remain in the
Desktop `codex` folder; the upload flow uses the copies stored in this project.
