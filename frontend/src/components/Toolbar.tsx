import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ValidationResult } from '../features/workflow/ValidationPanel';
import { HelpIcon } from './HelpIcon';
import { UserAvatar } from './UserAvatar';
import { ToolbarMenu } from './ToolbarMenu';
import { CommandPalette } from './CommandPalette';
import type { ActionItem } from './actions';

interface Props {
  workflowName: string;
  onNew: () => void;
  onSave: () => void;
  onOpen: () => void;
  onOpenExamplePicker: () => void;
  onValidate: () => void;
  onGenerate: () => void;
  onRefine: () => void;
  canRefine?: boolean;
  onSimulate: () => void;
  onEditJson: () => void;
  onNameChange: (name: string) => void;
  isValidating?: boolean;
  validationResult?: ValidationResult | null;
  isDark?: boolean;
  onToggleTheme?: () => void;
  onUndo?: () => void;
  onRedo?: () => void;
  canUndo?: boolean;
  canRedo?: boolean;
  onReport?: () => void;
  onHistory?: () => void;
  onTests?: () => void;
  onMermaid?: () => void;
  onExplain?: () => void;
  onSuggest?: () => void;
  onSafety?: () => void;
  onCloud?: () => void;
  onAbout?: () => void;
  onExportCode?: () => void;
}

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);
const MOD = IS_MAC ? '⌘' : 'Ctrl';

export function Toolbar(props: Props) {
  const {
    workflowName, onNew, onSave, onOpen, onOpenExamplePicker, onValidate, onGenerate, onRefine, canRefine = false,
    onSimulate, onEditJson, onNameChange, isValidating, validationResult, isDark = true, onToggleTheme,
    onUndo, onRedo, canUndo = false, canRedo = false, onReport, onHistory, onTests, onMermaid, onExplain,
    onSuggest, onSafety, onCloud, onExportCode, onAbout,
  } = props;

  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const closeMenu = useCallback(() => setOpenMenu(null), []);

  const hasErrors = validationResult && !validationResult.valid;
  const hasWarnings = validationResult?.warnings.length;

  // Ctrl/⌘+K opens the palette from anywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setOpenMenu(null);
        setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  const menus = useMemo(() => {
    const file: ActionItem[] = [
      { id: 'doc:new', label: 'New workflow', group: 'File', hint: 'Start from an empty workflow', onSelect: onNew },
      { id: 'doc:open', label: 'Open file…', group: 'File', hint: 'Open a workflow JSON file', onSelect: onOpen },
      { id: 'doc:save', label: 'Save to file…', group: 'File', hint: 'Download the workflow as a JSON file', onSelect: onSave },
      { id: 'store:cloud', label: 'Cloud workflows…', group: 'File', hint: 'Save to your account, version history and share links', onSelect: onCloud, disabledReason: 'Not available' },
      { id: 'store:examples', label: 'Examples…', group: 'File', hint: 'Browse example workflows', onSelect: onOpenExamplePicker },
    ];
    const exportItems: ActionItem[] = [
      { id: 'data:json', label: 'Edit JSON', group: 'Export', hint: 'View and edit the workflow JSON', onSelect: onEditJson },
      { id: 'data:code', label: 'Code (Python, LangGraph, MCP)', group: 'Export', hint: 'Export a runnable project, or import one', onSelect: onExportCode, disabledReason: 'Not available' },
      { id: 'data:mermaid', label: 'Mermaid diagram', group: 'Export', hint: 'Export or import a Mermaid diagram', onSelect: onMermaid, disabledReason: 'Not available' },
      { id: 'data:report', label: 'Report', group: 'Export', hint: 'Export a report of the workflow and its last run', onSelect: onReport, disabledReason: 'Not available' },
    ];
    const analyze: ActionItem[] = [
      { id: 'check:explain', label: 'Explain', group: 'Analyze', hint: 'Plain-language description of this workflow', onSelect: onExplain, disabledReason: 'Not available' },
      { id: 'check:suggest', label: 'Suggest changes', group: 'Analyze', hint: 'Fixes for design findings and AI-proposed edits', onSelect: onSuggest, disabledReason: 'Not available' },
      { id: 'check:safety', label: 'Safety checks', group: 'Analyze', hint: 'Prompt-injection exposure and failure drill', onSelect: onSafety, disabledReason: 'Not available' },
      { id: 'history:runs', label: 'Run history', group: 'Analyze', hint: 'Saved simulation runs', onSelect: onHistory, disabledReason: 'Not available' },
    ];
    const help: ActionItem[] = [
      { id: 'help:search', label: 'Search actions', group: 'Help', hint: 'Find any action by name', shortcut: `${MOD} K`, onSelect: () => setPaletteOpen(true) },
      { id: 'about:about', label: 'About AiFlow', group: 'Help', hint: 'Version, what is new, and version info for bug reports', onSelect: onAbout, disabledReason: 'Not available' },
    ];
    return { file, export: exportItems, analyze, help };
  }, [onAbout, onNew, onOpen, onSave, onCloud, onOpenExamplePicker, onEditJson, onExportCode, onMermaid, onReport, onExplain, onSuggest, onSafety, onHistory]);

  // Everything, for the palette: the menu items plus the actions that sit directly on the bar.
  const allActions = useMemo<ActionItem[]>(() => [
    { id: 'run:validate', label: 'Validate', group: 'Check', hint: 'Check the structure and the design findings', onSelect: isValidating ? undefined : onValidate, disabledReason: 'Already validating' },
    { id: 'run:simulate', label: 'Simulate', group: 'Run', hint: 'Run the workflow with test data', onSelect: onSimulate },
    { id: 'run:tests', label: 'Tests', group: 'Run', hint: 'Test suites: check the workflow against many inputs', onSelect: onTests, disabledReason: 'Not available' },
    { id: 'ai:generate', label: 'Generate with AI', group: 'AI', hint: 'Create a workflow from a description', onSelect: onGenerate },
    { id: 'ai:refine', label: 'Refine with AI', group: 'AI', hint: 'Improve this workflow with AI', onSelect: canRefine ? onRefine : undefined, disabledReason: 'Build a workflow first to refine it' },
    { id: 'edit:undo', label: 'Undo', group: 'Edit', shortcut: `${MOD} Z`, onSelect: canUndo ? onUndo : undefined, disabledReason: 'Nothing to undo' },
    { id: 'edit:redo', label: 'Redo', group: 'Edit', shortcut: `${MOD} Y`, onSelect: canRedo ? onRedo : undefined, disabledReason: 'Nothing to redo' },
    ...menus.file, ...menus.export, ...menus.analyze, ...menus.help.filter((h) => h.id !== 'help:search'),
    { id: 'view:theme', label: isDark ? 'Switch to light mode' : 'Switch to dark mode', group: 'View', onSelect: onToggleTheme },
  ], [menus, isValidating, onValidate, onSimulate, onTests, onGenerate, canRefine, onRefine, canUndo, onUndo, canRedo, onRedo, isDark, onToggleTheme]);

  const menuProps = (id: string) => ({
    open: openMenu === id,
    onToggle: () => setOpenMenu((cur) => (cur === id ? null : id)),
    onHover: () => setOpenMenu((cur) => (cur === null ? cur : id)),   // only switches while one is already open
    onClose: closeMenu,
  });

  return (
    <header className="toolbar">
      <div className="toolbar-brand">
        <span className="toolbar-logo">⬡</span>
        <span className="toolbar-name">AiFlow</span>
        <HelpIcon
          title="AiFlow — Workflow Designer"
          body={`AiFlow is a visual tool for designing AI agent workflows. Name your workflow in the input field, build it on the canvas, then validate, simulate, and export it.\n\nUse Generate to create a workflow from a plain-English description, or File → Examples to load a pre-built workflow.\n\nPress ${MOD}+K to search every action.`}
        />
      </div>

      <input
        className="toolbar-workflow-name"
        value={workflowName}
        onChange={(e) => onNameChange(e.target.value)}
        title="Workflow name"
        aria-label="Workflow name"
      />

      <div className="tb-group" role="group" aria-label="History">
        <button className="btn btn-ghost tb-icon" onClick={onUndo} disabled={!canUndo} title={`Undo (${MOD}+Z)`} aria-label="Undo">↶</button>
        <button className="btn btn-ghost tb-icon" onClick={onRedo} disabled={!canRedo} title={`Redo (${MOD}+Y)`} aria-label="Redo">↷</button>
      </div>

      <nav className="tb-group" aria-label="Menus">
        <ToolbarMenu label="File" items={menus.file} {...menuProps('file')} />
        <ToolbarMenu label="Export" items={menus.export} {...menuProps('export')} />
        <ToolbarMenu label="Analyze" items={menus.analyze} {...menuProps('analyze')} />
        <ToolbarMenu label="Help" items={menus.help} {...menuProps('help')} />
      </nav>

      <div className="tb-group" role="group" aria-label="Check and run">
        <button
          className={`btn btn-ghost validate-btn${hasErrors ? ' validate-btn--error' : hasWarnings ? ' validate-btn--warn' : ''}`}
          onClick={onValidate}
          disabled={isValidating}
          title="Check the structure and the design findings"
        >
          {isValidating ? 'Validating…' : 'Validate'}
          {hasErrors && <span className="validate-badge validate-badge--error">{validationResult.errors.length}</span>}
          {!hasErrors && hasWarnings && <span className="validate-badge validate-badge--warn">{validationResult!.warnings.length}</span>}
        </button>
        <button className="btn btn-ghost tb-run" onClick={onSimulate} title="Simulate workflow">▶ Simulate</button>
        <button className="btn btn-ghost" onClick={onTests} disabled={!onTests} title="Test suites: check the workflow against many inputs">Tests</button>
      </div>

      <div className="toolbar-actions">
        <button className="tb-search" onClick={() => { setOpenMenu(null); setPaletteOpen(true); }} aria-label="Search actions" title={`Search actions (${MOD}+K)`}>
          <span aria-hidden="true">⌕</span>
          <span className="tb-search-label">Search actions</span>
          <kbd className="tb-kbd">{MOD} K</kbd>
        </button>
        <button
          className="btn btn-ghost"
          onClick={onRefine}
          disabled={!canRefine}
          title={canRefine ? 'Refine this workflow with AI' : 'Build a workflow first to refine it'}
        >
          Refine
        </button>
        <button className="btn btn-primary" onClick={onGenerate} title="Create a workflow from a description">Generate</button>
        <button
          className="btn btn-theme"
          onClick={onToggleTheme}
          title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
          aria-label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {isDark ? '☀' : '☾'}
        </button>
        <UserAvatar />
      </div>

      {paletteOpen && <CommandPalette actions={allActions} onClose={() => setPaletteOpen(false)} />}
    </header>
  );
}
