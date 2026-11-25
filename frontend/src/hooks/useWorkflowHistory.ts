import { useState, useCallback } from 'react';
import type { Workflow } from '../models/workflow';

const MAX_HISTORY = 50;

/** The canvas reports a "change" for things that are not one (every step's position when it first lays out). */
const sameWorkflow = (a: Workflow, b: Workflow) => a === b || JSON.stringify(a) === JSON.stringify(b);

interface HistoryState {
  stack: Workflow[];
  cursor: number;
}

export function useWorkflowHistory(initial: Workflow | (() => Workflow)) {
  const [history, setHistory] = useState<HistoryState>(() => ({
    stack: [typeof initial === 'function' ? initial() : initial],
    cursor: 0,
  }));

  const workflow = history.stack[history.cursor];

  // Push a new state onto the stack, erasing any redo branch.
  const setWorkflow = useCallback((wfOrUpdater: Workflow | ((current: Workflow) => Workflow)) => {
    setHistory(prev => {
      const current = prev.stack[prev.cursor];
      const next = typeof wfOrUpdater === 'function' ? wfOrUpdater(current) : wfOrUpdater;
      if (sameWorkflow(current, next)) return prev;          // nothing changed: no undo step, no "unsaved changes"
      const base = prev.stack.slice(0, prev.cursor + 1);
      const newStack = [...base, next].slice(-MAX_HISTORY);
      return { stack: newStack, cursor: newStack.length - 1 };
    });
  }, []);

  // Replace entire history with a single entry (New / Open / Load Example).
  const reset = useCallback((wf: Workflow) => {
    setHistory({ stack: [wf], cursor: 0 });
  }, []);

  const undo = useCallback(() => {
    setHistory(prev =>
      prev.cursor > 0 ? { ...prev, cursor: prev.cursor - 1 } : prev,
    );
  }, []);

  const redo = useCallback(() => {
    setHistory(prev =>
      prev.cursor < prev.stack.length - 1
        ? { ...prev, cursor: prev.cursor + 1 }
        : prev,
    );
  }, []);

  return {
    workflow,
    setWorkflow,
    reset,
    undo,
    redo,
    canUndo: history.cursor > 0,
    canRedo: history.cursor < history.stack.length - 1,
  };
}
