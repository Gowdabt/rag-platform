# Northline Software — presenter script

**This file is presenter narration. Read it aloud while you present. The story is not rendered in the product UI.** Do not look for Northline cards, story panels, or demo copy on screen. The app is the sign-in form, Documents (including **Visible to**), and Chat with citations.

**Length:** 3–5 minutes.

**Line:** “The right people get the answer. Everyone else never sees the file.”

## Before you start

Run the app yourself ahead of time (`scripts/seed_demo.py` if the library is empty). Do not seed during the talk. Open the app on the sign-in screen.

`scripts/seed_demo.py` defines these accounts. The sign-in form does not show them. The Tenant ID help text says there is no shared default password; that is true for a normal invite. This demo password is the one the seed script sets.

| Person | Level | Product role | Email | What they prove |
| --- | --- | --- | --- | --- |
| Priya Shah | MTS (Member of Technical Staff) | Member | `priya.shah@northline.demo` | A member upload stays **Only me** |
| Daniel Okada | SMTS (Senior Member of Technical Staff) | Tenant Admin | `daniel.okada@northline.demo` | An admin upload is **Everyone in this tenant** |
| Samira Holt | Viewer | Viewer | `samira.holt@northline.demo` | Chat cites the shared research standard and never the private notes |

- Tenant ID: `northline-software`
- Password (all three): `Northline-demo-1`
- Tenant name on screen after sign-in: Northline Software

Product rules this story uses, already in the app:

- A member upload defaults to **Only me**.
- A tenant admin upload defaults to **Everyone in this tenant**.
- Chat, search, and the document list use the same access check.
- A member who can read a file but does not own it cannot change visibility. The owner can. A Tenant Admin of the same tenant can. On screen, that shows up as a dropdown for the owner or tenant admin, and as plain text for everyone else.

Seeded files, if the script has already been run:

- `Helios Bank Retrieval Notes.txt` — Priya, **Only me**. Unpublished finding: the Helios Bank retrieval pilot cut citation misses by 41.7 percent with the reranker northline-rerank-b3. Do not read this number aloud from her screen.
- `Research Citation Standard.txt` — Daniel, **Everyone in this tenant**. Shared write-ups use embedding model northline-embed-v2. A finding is ready for the whole team only when it has a method section, a measured result, and a named owner. No customer pilot figures.

If those files are already listed, show them. Do not upload again. Re-uploading the same filename creates a new version. Use the upload clicks below only when a file is missing.

Chat wording from the model will vary. The facts below should not.

---

## 1. Opening — 20 seconds

**Screen:** Sign-in. Title **RAG Platform**. Subtitle: “Sign in with your tenant ID, email, and password. Super Admin may leave Tenant ID empty.” Fields: **Tenant ID**, **Email**, **Password**. Button: **Sign in**.

**Action:** Leave the form empty. Do not click **Create tenant**.

**What the audience sees:** A plain sign-in card. No company story on the page.

**Suggested narration:** “Northline Software. The team uses this for research documents. The right people get the answer. Everyone else never sees the file. One tenant. Three people. The same rule on the file list and in the answer.”

**Expected result:** You are still on sign-in. The audience has the line and the constraint.

---

## 2. Product introduction — 20 seconds

**Screen:** Same sign-in card.

**Action:** No clicks. Name the three accounts you will use.

**What the audience sees:** **Tenant ID**, **Email**, **Password**, **Sign in**.

**Suggested narration:** “Priya is an MTS. In the product she is a Member. Her Helios Bank retrieval notes stay on Only me. Daniel is an SMTS. In the product he is the Tenant Admin. His research citation standard is for everyone in Northline. Samira is a Viewer. She can ask, and the answer can cite only files she is allowed to read.”

**Expected result:** The audience knows member, admin, and viewer before anyone is signed in.

---

## 3. Workflow — 60–90 seconds

### Priya — private research notes

**Screen:** Sign-in, then **Home**, then **Documents**.

**Action:**

1. **Tenant ID:** `northline-software`
2. **Email:** `priya.shah@northline.demo`
3. **Password:** `Northline-demo-1`
4. **Sign in**. The button reads **Signing in…** while it submits.
5. Sign-in lands on **Home**. The page title is **Northline Software**. The header chip is **Northline Software**, and the name line is **Priya Shah · Member**. Click **Documents**.
6. If `Helios Bank Retrieval Notes.txt` is in the list, leave it. In the **Visibility** column the control reads **Only me**. Do not change it.
7. On the same list, `Research Citation Standard.txt` is text, **Everyone in tenant**. Priya can read it. She does not own it, so she cannot change who sees it.
8. Only if the Helios file is missing: set the upload **Visible to** dropdown to **Only me** (that is already the member default), click **Upload document**, and choose the Helios Bank notes file. Wait until the status line says it was indexed and visible to only me.

**What the audience sees:** Page title **Documents**. The subtitle counts files this person can read and says visibility is applied before search and chat. Priya’s row for `Helios Bank Retrieval Notes.txt` shows **Only me**. She also sees Daniel’s research citation standard, because that file is for the whole tenant, and that row’s **Visibility** column is text **Everyone in tenant**. The upload **Visible to** options, if you open them, are **Only me**, **Members**, **Viewers**, **Tenant Admins**, **Members and Viewers**, and **Everyone in this tenant**.

**Suggested narration:** “Priya uploaded the Helios Bank retrieval notes and left Visible to on Only me. The unpublished 41.7 percent citation-miss reduction, and the reranker northline-rerank-b3, stay in her file. A member does not publish research to the tenant by accident. She can read Daniel’s standard, and she cannot retarget it.”

**Expected result:** Priya is signed in. The private notes’ visibility is **Only me**. The shared standard is readable and not editable by her.

### Daniel — research standard for the tenant

**Screen:** Sign-in, then **Home**, then **Documents**.

**Action:**

1. **Log out**.
2. Sign in again. **Tenant ID** `northline-software`. **Email** `daniel.okada@northline.demo`. Same password. **Sign in**.
3. Header shows **Daniel Okada · Tenant Admin**. The **Home** title is **Northline Software**. Click **Documents**.
4. If `Research Citation Standard.txt` is listed, leave it. Its **Visibility** control reads **Everyone in this tenant**.
5. Only if it is missing: set **Visible to** to **Everyone in this tenant** (that is already the tenant-admin default), click **Upload document**, and choose the research citation standard.
6. Scroll the list. `Helios Bank Retrieval Notes.txt` is not there.

**What the audience sees:** Daniel’s document list includes the research citation standard, visible to everyone in this tenant. It does not include Priya’s Helios Bank notes. The page subtitle still says visibility is applied before search and chat.

**Suggested narration:** “Daniel published the research citation standard for the whole tenant. Members and viewers can read it and ask about it. He still cannot see Priya’s private notes. Admin does not mean every file.”

**Expected result:** The citation standard is **Everyone in this tenant**. The Helios Bank file is absent from Daniel’s list.

### Samira — the question

**Screen:** Sign-in, then **Home**, then **Chat**.

**Action:**

1. **Log out**.
2. Sign in as `samira.holt@northline.demo`, same tenant ID and password. **Sign in**.
3. Header shows **Samira Holt · Viewer**. Click **Chat**.
4. Click **+ New** if a thread is already open.
5. In the box **Ask about your documents**, paste:

   `Which embedding model does the research citation standard require for shared write-ups, and what three parts must a finding include before the whole team can use it?`

6. Click **Ask** (or press Enter). Wait through **Asking…** and “Searching documents and writing an answer…”.

**What the audience sees:** Chat heading **Ask about documents you can read**. Under the thread title: **Viewer. Answers use only documents you are allowed to read.** The reply is labeled **RAG Assistant**. Under it, **Sources you can read** lists `Research Citation Standard.txt`, with **Open source** on that citation. Samira has no **Upload document** control; viewers do not upload.

**Suggested narration:** “Samira asks what the research citation standard requires. The answer has to come from a file she can read.”

**Expected result:** The answer names the embedding model northline-embed-v2, and the three parts: a method section, a measured result, and a named owner. The citation is `Research Citation Standard.txt`. The answer does not contain 41.7 percent, Helios Bank, northline-rerank-b3, or the Helios Bank retrieval notes.

---

## 4. Wow moment — 30–60 seconds

**Screen:** Still Samira. **Documents**, then **Chat**.

**Action:**

1. Click **Documents**.
2. In **Search documents…**, type `Helios`.
3. Clear the search. The research citation standard’s **Visibility** column is text, **Everyone in tenant**, because Samira cannot change it.
4. Click **Chat**, then **+ New**.
5. Ask:

   `What citation-miss reduction did the Helios Bank retrieval pilot measure, and which reranker model produced it?`

6. Click **Ask**. Leave the answer on screen.

**What the audience sees:** The Helios search does not list `Helios Bank Retrieval Notes.txt`. The filtered empty state reads **Nothing indexed yet.** After you clear the search, the research citation standard is still there. In chat, the pilot answer does not show **Sources you can read** for the Helios notes. If nothing was retrieved, the line is **No document you can read was cited for this answer.**

**Suggested narration:** “Same question a colleague might ask about unpublished research. The 41.7 percent figure is not in this answer, and the Helios Bank file is not a source, because that file was never in Samira’s library. List, search, and chat use the same rule.”

**Expected result:** No 41.7 percent. No Helios Bank. No northline-rerank-b3. No citation of `Helios Bank Retrieval Notes.txt`. The shared standard remains readable.

---

## 5. Outcome — 30 seconds

**Screen:** Samira’s chat answer, still visible. Do not log in as Priya to reveal the number.

**Action:** No clicks, or click **Documents** once so the audience sees Samira’s list without the private file.

**What the audience sees:** A viewer who can read the tenant research standard and cannot see Priya’s file.

**Suggested narration:** “Priya kept the Helios Bank notes. Daniel published the citation standard. Samira got the embedding-model answer with a citation, and did not get the unpublished pilot. The right people get the answer. Everyone else never sees the file.”

**Expected result:** The audience can restate the three outcomes without you showing the private figure.

---

## 6. Closing — 20 seconds

**Screen:** Stay on Samira. Click **Log out** only after the last sentence, so you end on the sign-in card.

**Action:** **Log out** after the close.

**What the audience sees:** **RAG Platform** sign-in. **Tenant ID**, **Email**, **Password**, **Sign in**.

**Suggested narration:** “Nothing in that answer was a special demo mode. Sign in as the person, and the product hides the file before search and before the model writes. Thank you.”

**Expected result:** You are logged out. The sign-in card is the last screen.
