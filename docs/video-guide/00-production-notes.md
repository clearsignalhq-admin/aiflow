# Production notes

## Voice and wording

- **Plain language.** The viewers design and check workflows; they do not necessarily program. Say "step" for a box on the canvas and "connection" for an arrow. Say "AI model" rather than jargon.
- **Say what you see.** Narrate the thing on screen at that moment, then say why it matters. Do not describe buttons that are not visible.
- **Use the product's own words**, exactly as they appear in the interface: *Validate*, *Simulate*, *Suggest changes*, *Safety checks*, *Cloud workflows*, *Share*, *Compare with*, *Run failure drill*. Menu paths are said as "File, then Examples".
- **Be honest about limits.** The safety checks show where a workflow is exposed; they do not prove it is safe. Simulations use made-up data, not the real model, unless the viewer chooses otherwise. Say so where it comes up.
- **No promises about the future** and no comparisons with other products.
- Numbers on screen: read them as they appear ("one hundred percent, three of three"). Keep the example the same across videos: **Supply Chain Monitor**.

## Pacing

- About 150 words a minute; leave a short pause when the screen changes.
- Each scene is 15 to 30 seconds. If a scene runs long, cut words, not the picture.
- The narration fills roughly three quarters of each timeline (about 2½ to 3 minutes of speech in a 3 to 4 minute video). The rest is for pauses and for the on-screen actions. If a tool paces the speech itself, expect the finished video to be a little shorter than the stated length.
- Zoom or highlight the part of the screenshot named under *On screen*; the rest of the screen is context.

## Words to pronounce

| Written | Say |
| --- | --- |
| AiFlow | "A-I-flow" |
| LLM | "L-L-M", or "AI model" |
| HITL / Human Review | "human review" |
| RAG | "retrieval step" (first time: "RAG, which means looking things up in a knowledge base") |
| JSON | "jason" |
| MCP | "M-C-P" |
| Ctrl+K | "Control K" (on a Mac, "Command K") |

## Using the storyboards with Google NotebookLM

1. Create a notebook and add the video's storyboard (for example `01-quick-start.md`) as a source. Add `../user-guide/README.md` as a second source so the tool can check facts against the guide.
2. If your version accepts images as sources, add the screenshots named in the storyboard too. Otherwise the storyboard's scene list is enough: it names every screenshot by file name, so you can place them yourself when you assemble the video.
3. Paste this into the tool's customisation or instruction box:

> Make a short narrated video that follows the storyboard exactly: one section per scene, in the same order, using the scene titles as slide titles. Use the narration text as written (you may smooth the wording but do not add features, numbers or claims that are not in the storyboard or the user guide). Speak in a calm, friendly, plain-spoken style for people who design workflows but may not write code. Mention the on-screen notes as visual emphasis. Keep to the length given at the top of the storyboard. Finish with the one-line summary.

4. Listen once against the storyboard. Anything the tool added that is not in the storyboard or the guide should be removed or re-recorded.

## Checklist before publishing a video

- [ ] The screenshots match the current interface (compare with the live app).
- [ ] Every menu path and button name in the narration exists exactly as spoken.
- [ ] Nothing on screen shows a real person's email, a real key or a real customer name (the screenshots use a demo user and made-up data).
- [ ] Captions are on, and the chapter markers are in the description.
- [ ] The video is linked from the user guide's introduction and the landing page.
