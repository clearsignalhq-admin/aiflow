// The examples the picker offers. Everything except the files themselves is read from the files.
// ── Static example catalog ───────────────────────────────────────────
import emailAutoReply        from '../../../../examples/easy/email-auto-reply.json';
import sentimentClassifier   from '../../../../examples/easy/sentiment-classifier.json';
import dataEnrichment        from '../../../../examples/easy/data-enrichment.json';
import meetingNotes          from '../../../../examples/easy/meeting-notes.json';
import customerSupport       from '../../../../examples/medium/customer-support.json';
import contentModeration     from '../../../../examples/medium/content-moderation.json';
import invoiceProcessing     from '../../../../examples/medium/invoice-processing.json';
import refundRequest         from '../../../../examples/medium/refund-request.json';
import hrOnboarding          from '../../../../examples/medium/hr-onboarding.json';
import aiResearchAgent       from '../../../../examples/complex/ai-research-agent.json';
import supplyChainMonitor    from '../../../../examples/complex/supply-chain-monitor.json';
import multiAgentJourney     from '../../../../examples/complex/multi-agent-customer-journey.json';

export interface ExampleEntry {
  json: object;
  difficulty: 'easy' | 'medium' | 'complex';
  industry: string;
  nodeCount: number;
  tags: string[];
}

interface ExampleFile {
  nodes: unknown[];
  metadata: { difficulty: ExampleEntry['difficulty']; industry: string; tags: string[] };
}

/** Difficulty, industry, tags and the step count all come from the example file itself. */
function entry(json: object): ExampleEntry {
  const file = json as ExampleFile;
  return { json, difficulty: file.metadata.difficulty, industry: file.metadata.industry, nodeCount: file.nodes.length, tags: file.metadata.tags };
}

export const CATALOG: ExampleEntry[] = [
  emailAutoReply, sentimentClassifier, dataEnrichment, meetingNotes,
  customerSupport, contentModeration, invoiceProcessing, hrOnboarding, refundRequest,
  aiResearchAgent, supplyChainMonitor, multiAgentJourney,
].map(entry);
