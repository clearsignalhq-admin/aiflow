# Example workflows

Twelve ready-made workflows, shown in the app under **File → Examples…**. They are meant to be read, run and copied. The picker reads each file's difficulty, industry, tags and step count from the file itself, so adding a workflow means adding one JSON file here and listing it in `frontend/src/features/workflow/ExamplePickerModal.tsx` (a test fails if a file is not listed).

Every example validates, simulates cleanly on every seed, passes the design checks, and exports to valid code. These properties are enforced by `backend/tests/test_examples.py`. **Supply Chain Monitor is the one exception, on purpose** (see below).

## The examples

| Example | Level | What it shows |
| --- | --- | --- |
| **Email Auto-Reply** | Easy | One model step between Start and End, with a declared output so the made-up reply looks like a reply |
| **Sentiment Classifier** | Easy | A model step whose answer is one of a fixed list, routed by a decision |
| **Data Enrichment Pipeline** | Easy | An outside lookup, a transform, and a failure branch that ends cleanly instead of passing bad data on |
| **Meeting Notes to Action Items** | Easy | Model, transform and tool in one short flow; the tool step is checked so a failed post is reported |
| **Customer Support Agent** | Medium | Classification, knowledge-base search, a customer lookup, and a human review for complex cases |
| **Content Moderation Pipeline** | Medium | Policy retrieval, a model judgement, and a human moderator for flagged content |
| **Invoice Processing & Approval** | Medium | An approval threshold, a manager review, and an ERP write whose failure goes to finance instead of being lost |
| **HR Employee Onboarding** | Medium | A manager signs off **before** accounts are created; a failure afterwards goes to IT |
| **Refund Request Handler** | Medium | The safe pattern: the model classifies, a person approves, and only then does money move. Compare its Safety checks with Supply Chain Monitor's |
| **AI Research Agent** | Complex | Retrieval plus a web search, with a graceful fallback when the search fails, and an expert review of low-confidence findings |
| **Multi-Tier Customer Journey** | Complex | Two tracks (premium and basic); every message a model writes is checked by a person, and failed lookups and deliveries are handled |
| **Supply Chain Monitor** | Complex | **Deliberately left with four design findings and a safety exposure.** The user guide and video storyboards use it to demonstrate Validate, Suggest changes and Safety checks |

## Conventions the examples follow

- **Failure handling.** Every API, database and tool step is followed by a check of its success flag (`output.ok`). The step declares `ok` as a true/false value that is always true in a simulation, so the success path runs unless a failure is injected. A failed step ends the run cleanly or goes to a person; it never carries on with bad data.
- **A person before anything changes.** A model's answer never reaches a write (a payment, an account, a message to a customer) without a human review in between. A review on a failure branch is a follow-up, not an approval.
- **Data contracts.** Steps whose output later steps read declare an output schema, so simulations produce realistic fields and the checks can tell when a field is missing.
- **No secrets.** Credentials are references such as `Bearer env:PAYMENTS_API_TOKEN` or `env:DB_URL`, never values.
- **Decisions are labelled.** Every outgoing connection of a decision has a label that its expression can produce.
- **A sample input.** `metadata.sample_input` gives Simulate something to start with.

## Things to try

- Load **Supply Chain Monitor**, press **Validate**, then **Analyze → Suggest changes → Apply all**. The four findings go away, and the workflow is tidied.
- Open **Analyze → Safety checks** on Supply Chain Monitor and on **Refund Request Handler**, and compare the exposure severities.
- On any example, run the **failure drill**: steps with a check report "handled" or "stops"; Supply Chain Monitor reports failures as "not noticed".
- Press **Tests → + Add case from sample input** to turn an example's sample input into a test case, then add a check such as *Visits step*.
- **Export → Code** on **Customer Support Agent** to see how a workflow becomes a runnable project.
