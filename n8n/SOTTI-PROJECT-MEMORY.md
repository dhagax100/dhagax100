# SOTTI Customer Care Automation: Project Memory

Last updated: 2026-11-11. Read this first in any new session. Keep it current.
No secrets here. Tokens and keys live only in n8n credentials.

## 1. Who and what
- **User:** building automation prototypes for a client, learning AI automation, beginner level. Pronouns: use they/them.
- **Client:** SOTTI (Somali Technical Training Institute), also written STI, in Mogadishu. A TVET school.
- **Courses (test data):** Mechanic (auto mechanic), Electric (electrical skill), Mobile (mobile repair).
- **Client system:** Odoo (version, hosting and plan not yet confirmed).
- **Five problem domains:** 1) getting and keeping students (enrollment), 2) academics (attendance, exams), 3) finance, 4) funding and grants, 5) HR.
- **Current focus:** domain 1, **customer care**, to raise enrollment.
- **Org chart:** `n8n/sotti-structure.md` (locked, read-only; change only when the user asks).
- **Goal:** deliver working prototypes of everything that will be used in production. No "later" features.

## 2. How to work with the user (important)
- Be **short, clear, on point**. Lead with the answer. Plain words.
- **One small step at a time.** Wait for "next" or a screenshot before the following step. Never dump many steps.
- Answer **only the question asked**. No generic or long responses. The user gets frustrated by them.
- Explain with a small example. When asked for a concept, go in numbered parts and wait for "next".
- Give exact text to paste in code blocks. Say which field and which tab.
- The user sends screenshots. Read them closely and name what is right and what is wrong.
- Be honest when unsure. Do not invent facts or book contents. Cite sources with links when researching.
- Somali messages to students: simple Somali, short, WhatsApp-friendly.
- The user asked for: originality, explainability, transparency.
- Do not suggest email as a channel (the user said no email).

## 3. Customer care model (agreed)
**4 doors, 3 needs, 1 record.**
- Doors: Comment, DM, Form (goes with every video), Walk-in. Calls also happen.
- Needs: Get info, Enroll, Location.
- Every person is **one row**, keyed by **phone number**. Status says where they are.
- Staff share work with **Assigned to = Agent1 / Agent2** (roles, not names) and per-agent filter views. No separate sheet per stage.
- Industry term: CRM. Contacts table + Interactions (activity log) table.
- Interaction = any event in either direction: comment, DM, call, form, walk-in, our auto reply or reminder, staff note, status change. One event = one line; never edit old lines.

### Statuses (approved)
`New → Info request → Visited → Ready to enroll → Enrolled → Started → Finished → Graduated`
Exits: `Cold`, `Cancelled`. One status at a time.

### Approved columns (to be created; not yet built)
- **Contacts** (one row per person): Phone (key), Name, Location, Course, Source (Form/DM/Comment/Walk-in), Status, Assigned to, Last contact, Next follow-up, Reminders, Created, Notes.
- **Interactions** (one row per event): Date and time, Phone, Channel (Comment/DM/Call/Form/Walk-in), Direction (In/Out), Summary, Handled by (Agent1/Agent2/Automation), Outcome (Info sent/No answer/Visit booked...).
- **Dropdowns** tab: lists for Status, Source, Channel, Outcome, Assigned to.
- Better follow-up design (from the n8n template): store **Next follow-up date** in the row; the daily job asks "whose date is today?".

### Assumptions about Mogadishu (verify with the client)
WhatsApp is the main channel; voice notes are common; many prefer calls; fees via mobile money (EVC Plus); Somali language, some English; family joins decisions. Voice notes need transcription; left out of the first prototype.

## 4. What is built (n8n Cloud, all tested in test mode, NOT published yet)
Google Sheet: **Lead Capture Database**. Tabs and columns:
- `Leads`: Number, Name, Location, Phone Number, Course, Status (Enroll form rows; Enrolled alert watches this tab).
- `Info`: Name, Location, Number, Course (s), Status, Last contact, Reminders.
- `Visit`: Visit form rows.
- `Courses` (knowledge base): Course, Content, Duration, Schedule, Fee, Location, Requirements, Contact. Test rows for Mechanic, Electric, Mobile. Course names must match the form values exactly.

### Workflow A: main form (n8n Form Trigger)
Page 1 dropdown: enroll / info / visit (Somali). A Switch sends each option to its branch.
- **Enroll:** details page → Sheets row (Leads, Status `Ready to enroll`) → Telegram alert to staff → WhatsApp payment message (fee 35 USD diiwaangelin + bisha koowaad, EVC Plus number, location Howlwadaag, send receipt) → Form Ending.
- **Info:** page → Sheets row (Info tab) → Telegram alert → Form Ending.
- **Visit:** page → Sheets row (Visit tab) → Telegram alert → Form Ending.
- Button labels: `Sii wad` (continue), `Dir` (send).

### Workflow B: "SOTTI - Enrolled Alert"
Google Sheets Trigger (Leads, row updated) → Switch on Status:
- `Enrolled`, `Started`, `Finished`, `Graduated`. Each branch: Get row(s) filtered by status (**Execute Once on**) → Code counts rows → Telegram to head with the total → WhatsApp message to the student (Somali).
- Wording: Finished = "dhameeyay", Graduated = "qalin jebiyay".
- All four branches tested.

### Workflow C: "STI - Info Journey"
Google Sheets Trigger (Info tab, row added) → Edit Fields (`CourseName = JSON.parse($json['Course (s)'])[0]`) → Get row in `Courses` (RAG-style lookup, Execute Once) → Basic LLM Chain (OpenRouter chat model; paid DeepSeek model in use; prompt holds the course facts, system prompt gives Somali style and "use only given facts") → WhatsApp send → Telegram staff alert → Update row (match on Name: Last contact = today, Reminders = 0).

### Workflow D: "STI - Info Follow-up"
Schedule 9am daily → Get rows (Info, Status = `Info request`) → Code computes `days` since Last contact and `action` → Switch:
- `reminder` (Reminders 0, days >= 2): WhatsApp reminder, then update Reminders = 1 and Last contact.
- `staff` (Reminders 1, days >= 5): Telegram alert to call, then update Reminders = 2 (Last contact unchanged).
- `last` (Reminders 2, days >= 8): final WhatsApp message, then Status = `Cold`, Reminders = 3.
- Full run with nobody due sends nothing (tested).

### Repo files (`n8n/`)
`sti-lead-capture.json`, `sti-ai-auto-reply.json` (early importable prototypes), `sotti-structure.md` (locked chart), this file.

## 5. Integrations
- **Google Sheets:** OAuth credentials in n8n.
- **Telegram:** bot `@n8n_with_dhagax_bot` (token in n8n). Staff alerts go to the user's own chat for now; later a staff group.
- **WhatsApp Cloud API (Meta):** developer account verified; app "SOTTI Automation"; business portfolio **Aranzone** (Meta blocked creating another). Using Meta's **free test number**. Test token **expires about every 24 hours**; regenerate on Meta's API Setup page and update the n8n credential (Business Account ID is the "Messaging account ID").
- **AI model:** OpenRouter. Free Gemma hit rate limits; paid DeepSeek works.

## 6. WhatsApp rules (learned)
- First message to someone who has not written in the last 24 hours must be an **approved template**. After they reply, free text works for 24 hours.
- Plan: one template with a button; tapping it opens the window; then the AI sends full details from the `Courses` tab.
- Test number only messages numbers added and verified in Meta. Production needs the institute's own number and business verification. Not done.

## 7. n8n lessons (this project)
- Drag fields into expressions; typing a field name by hand often fails.
- Unpin trigger data before testing a live multi-page form.
- A **disabled node passes data through**; nodes after it still run.
- A node that runs per item multiplies results; use **Execute Once** for counts.
- Google Sheets trigger only fires on a real change; to test, edit the trigger output (pencil icon) or change a different value.
- Test URL vs Production URL; workflows must be published to run alone.
- Form course checkbox saves as text like `["Mobile"]`; parse it or switch the field to a dropdown.
- Update-row nodes: delete empty fields so existing data is not overwritten.

## 8. Known issues and to-do before production
1. **Publish** all workflows; test with the production URLs.
2. **Permanent WhatsApp token**; own number; Meta business verification; **approved templates** for first contact and for Day 2/Day 8 messages.
3. Put the real **form link** in place of `[FORM LINK]`.
4. Info Journey matches rows by **Name**; switch to phone or ID.
5. Enrolled Alert fires on any edit of an Enrolled row; add a "notified" check.
6. Fix the course array text in the form (dropdown or parse).
7. Staff group chat ID instead of the user's own chat.
8. A native Somali speaker should review all message texts.
9. Test rows exist in the sheets; clean before the demo.
10. **Security:** an OpenRouter key preview appeared in a screenshot. Rotate it. Never paste keys in chat.
11. Privacy: send only what is needed to WhatsApp, Telegram, and the AI.

## 9. Roadmap (next)
1. Create `Contacts`, `Interactions`, `Dropdowns` tabs (approved columns) and move the **Info flow** onto them first, then Enroll and Visit.
2. **Walk-in and call log** form (staff, about 10 seconds per entry).
3. **Visit follow-up:** Day 1 thank-you, Day 4 "ready to enroll?", Day 7 staff alert, Day 10 `Cold`.
4. **Comment and DM auto-reply** (Meta): AI reads the message, classifies the need (info/enroll/location), replies in Somali, writes to Contacts and Interactions.
5. Enroll-side follow-up (Ready to enroll but unpaid), cancel-reason capture.
6. Reports: leads, replies, visits, enrollments, drop-off by source.
7. Assign work: auto-fill `Assigned to` Agent1/Agent2 by turns.
8. Production CRM: Odoo CRM (pipeline + chatter). n8n has an Odoo node. Check version, plan, API access, dedicated API user.
9. Later domains: academics (Odoo attendance), finance, funding, HR.
10. Post-prototype ideas: posting videos automatically (Facebook, TikTok via a scheduler), voice-note transcription.

## 10. Research found (verify before quoting to the client)
- Speed to lead: HBR study by Oldroyd et al. and Lead Response Management; the exact numbers vary across blogs. Direction is well supported.
- Education CRM practice: one record, timed follow-ups, segmenting, multichannel, track funnel. Sources are vendor blogs, so results claimed are marketing.
- Templates: [HubSpot free CRM spreadsheet](https://www.hubspot.com/business-templates/customer-relationship-management?m=1) (Contacts and Interactions tabs; we reviewed it), [n8n template 11233](https://n8n.io/workflows/11233-automate-lead-intake-and-crm-with-tally-forms-to-google-sheets-and-sendgrid-emails/) (Activity Log, next follow-up date), [n8n 15044](https://n8n.io/workflows/15044-automate-whatsapp-lead-capture-and-replies-with-whapi-ollama-and-sheets/), [n8n 9234](https://n8n.io/workflows/9234).
- Odoo: [CRM Basics video](https://odoo.com/slides/slide/crm-basics-scheduled-activities-moving-opportunities-7585) (not watched), [activities docs](https://www.odoo.com/documentation/16.0/applications/essentials/activities.html), WhatsApp-to-CRM modules exist ([whatsapp_lead_hook](https://apps.odoo.com/apps/modules/18.0/whatsapp_lead_hook)). No education-specific connector found.
- Book the user mentioned: "30 Agents Every AI Engineer Must Build" by Imran Ahmad (Packt). Full contents not seen; Ch. 14 Financial and Legal, Ch. 15 Education and Knowledge agents look relevant to later domains.
