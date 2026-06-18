# Notion Page LINEV2 (Task Tree) Formatting & Usage Guide

## Overview
The **LINEV2** page (also referenced as **LIVEV2** or `DFORGE_LINESV2_PAGE_ID` in the environment configuration) serves as the central Task Tree and source of truth for the YoncAgent system. It is a deeply hierarchical Notion page where your tasks are organized, tracked, and automatically enriched by AI.

This document details the structure, visual formatting rules, and conventions used on the LINEV2 page.

## 1. Structural Elements
The system parses the Notion page by building an in-memory tree. It relies on the natural indentation and block types provided by Notion:

- **Context Headings (`heading_1`, `heading_2`, `heading_3`) & Paragraphs:**
  Used to define the current context or "Theme Container". Any tasks nested under these headings or paragraphs will inherit this context.
- **Task Containers:**
  `bulleted_list_item`, `numbered_list_item`, `to_do`, `toggle`, and `quote` blocks are all treated as task nodes. 
- **Tree Depth:**
  Nesting blocks in Notion creates a strict parent-child relationship (e.g., placing a `to_do` inside a `toggle`, or indenting a bullet under another bullet).

## 2. Formatting Rules & Annotations

Tasks within LINEV2 are automatically enriched with specific emojis and tags by the YoncAgent pipeline. Understanding this format is key to reading the tree:

### a) Mode (Energy Level)
Each task is assigned an energy level (Mode) to indicate the physical or mental state required:
- `💻Focus` / `🧠Deep`: High cognitive load, requires a PC.
- `🧘Jail`: High focus without a PC (physical isolation).
- `Handy🤘🏻`: Physical/manual work, moderate cognition.
- `小Do📱`: Quick, active micro-tasks (phone-friendly).
- `🧟Zombie`: Low brain-power, mechanical/repetitive tasks.
- `Read` / `Watch👁‍🗨`: Passive visual consumption.
- `Listen`: Audio-only, can be done while walking/driving.
- `Draft`: Verbal/Drafting tasks.
- `Think🌩`: Pure mental deduction, zero physical action.

### b) Task Type (Functional Category)
Tasks are categorized by what kind of work they represent. Examples include:
- `🔍 测试` (Testing)
- `❓ 探索` (Exploration/Research)
- `🔧 修复` (Fixing/Bug resolution)
- *(And other custom types defined in your `YONCTASK_CONFIG`)*

### c) Priority Status
Based on the TIMELINER integration, root-level tasks receive priority markers to denote urgency and scheduling rank:
- `🔸`, `🔶`, `🟧`, `🏭`, `⬛` (From highest to lowest priority)

### d) Focus Indicator
The task you are actively working on (tracked via the Focus system) is marked with:
- `💪🏿💪🏿💪🏿` (Focus marker)

## 3. The Agent Pipeline Rules

When YoncAgent processes the LINEV2 page via the CLI (e.g., `python main.py sync --full`), it applies several automated rules that mutate the page format:

1. **Theme Matching & Reparenting:**
   The agent looks at the text and context headings of your tasks. If a task belongs to a specific theme (e.g., "Thesis", "SolarMan"), the agent will automatically move (reparent) the task under the correct Theme heading if it was placed incorrectly.
2. **WBS (Work Breakdown Structure) Classification:**
   Tasks are analyzed by the LLM and logically assigned a level from L1 (Highest level project) to L4 (Atomic, actionable step). 
3. **Auto-Decomposition (Split Suggestion):**
   If a task is classified as high-level (WBS < L4), is unchecked, and hasn't been split yet, the agent will automatically generate a breakdown of L4 atomic subtasks and insert them directly into your Notion page as children of the parent task.

## 4. Best Practices for Writing Tasks
To ensure the YoncAgent pipeline processes your LINEV2 page smoothly, adhere to these guidelines:

- **Keep atomic tasks actionable:** Start with a verb when possible. If an idea is too broad, just write it down and let the LLM decompose it for you.
- **Use Indentation:** Proper nesting is critical. If Task B is a step of Task A, ensure it is properly indented under Task A.
- **Avoid over-styling raw text:** The agent relies on plain text parsing and specific tags. While bolding and code blocks are fine, avoid manually adding pipeline emojis (like `💻Focus` or `💪🏿💪🏿💪🏿`) as the agent manages these automatically.
- **Use Context Headings:** Group related tasks under clear `heading_3` or toggles to help the Theme Pass algorithm correctly categorize them.
