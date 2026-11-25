# AiFlow Video Guide — storyboards

Four short videos, written as **storyboards**: for each scene there is a screenshot, what to emphasise on screen, and the narration to read or have generated. They are meant to be turned into videos with a tool such as Google NotebookLM, a slide deck or a screen recorder. The screenshots come from the user guide (`../user-guide/images`), so the videos always match the written guide.

| # | Video | Length | For someone who wants to… |
| --- | --- | --- | --- |
| 1 | [Quick start](01-quick-start.md) | about 3 minutes | open a workflow, check it, run it and save it |
| 2 | [Test suites and comparing runs](02-test-suites.md) | about 4 minutes | know whether a workflow still works after a change |
| 3 | [Safety checks](03-safety-checks.md) | about 3 minutes | find where a workflow is exposed to bad data or failing systems |
| 4 | [Saving, sharing and exporting](04-share-and-export.md) | about 3½ minutes | keep versions, share a link, and get working code |

Read [the production notes](00-production-notes.md) first: they hold the wording rules and the instructions to paste into NotebookLM.

## What a storyboard contains

Each scene looks like this:

- a heading with the scene number, title and its place in the timeline;
- the **screenshot** to show;
- **On screen**: what to zoom into, highlight or caption;
- **Narration**: the words to speak, written to be read aloud at a relaxed pace (about 150 words a minute).

Each video ends with **chapter markers** (for the video description) and a **one-line summary**.

## Keeping them current

The narration describes the interface as it is in the user guide. When the interface changes, regenerate the screenshots (`../user-guide/capture/README.md`), update the user guide, then adjust the scenes that mention the change. A test (`frontend/src/docs.test.ts`) fails if a storyboard points at a screenshot that does not exist.
