---
version: alpha
name: "StableAMD"
description: "Desktop-first local Radeon image studio with a quiet dark workbench, large visual canvas, and orange action accent."
colors:
  canvas: "#0B0D10"
  sidebar: "#101318"
  surface: "#14181E"
  surfaceRaised: "#191E25"
  surfaceStrong: "#20262E"
  border: "#2A313A"
  borderStrong: "#3A444F"
  text: "#F4F7FA"
  muted: "#97A2AF"
  accentOrange: "#EF6C45"
  accentOrangeHover: "#F57B55"
  success: "#61C892"
  warning: "#E9B75E"
  danger: "#EF6F79"
typography:
  sans:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Consolas, Liberation Mono, monospace"
rounded:
  DEFAULT: "0.75rem"
  sm: "0.5rem"
  md: "0.75rem"
spacing:
  workspace-gap: "1rem"
  page-gutter: "2rem"
components:
  navigation:
    density: "compact"
  workspace:
    layout: "recipe-canvas-inspector"
  inspector:
    disclosure: "details"
  buttons:
    accent: "orange"
---

# StableAMD Design System

## Overview

### Creative North Star

StableAMD should feel like a **desktop creative workstation**, closer to a photographer's dark editing desk or a GPU render console than a SaaS dashboard. The generated image is the artifact and receives the most space. Controls live around it as tools, not as a wall of equally weighted cards.

### Product context and register

- **Audience and primary job:** people generating and editing images locally on Radeon hardware; choose a generation type, provide the creative input, tune only the controls that matter, and inspect the result.
- **Usage scene:** desktop-first, frequently on large 1440p, ultrawide, or 4K monitors; mouse and keyboard are primary, but the UI must still recompose cleanly at laptop and phone widths.
- **Register:** product/tool. Utility and visual hierarchy win over brand decoration.
- **Memorable signature:** the Generate surface is a three-zone **recipe → canvas → inspector** workspace. The canvas dominates; the orange StableAMD accent marks committed actions and current work state.
- **Restraint:** no glassmorphism, decorative gradients, floating dashboard cards, or animation that delays work.
- **Anti-references:** generic AI dashboards with every option visible at once; form pages that become taller with every feature; game-like HUD chrome that competes with the generated image.
- **Token ownership/runtime mapping:** `DESIGN.md` records durable intent. Runtime values remain owned by `app/frontend/styles.css`, `compact-generate.css`, and `generate-workspace.css`; shared colors mirror the existing CSS variables rather than creating a second theme system.

## Colors

The interface stays near-black and neutral so generated artwork carries the chroma. `accentOrange` is reserved for primary actions, current mode emphasis, progress, and focus-adjacent cues. Success, warning, and danger keep their existing semantic meanings. Borders and tonal surfaces establish hierarchy before shadows do.

## Typography

Use the existing Inter/system stack for interface text. Headings are compact and slightly tightened; controls and metadata stay neutral and readable. Technical paths and diagnostics use the mono stack. Avoid all-caps section labels except tiny utility metadata where scanning benefits.

## Layout

Generate is desktop-first. On wide screens it uses three zones: a **recipe** column for model/prompt/source inputs, a flexible **canvas** for the current result, and a sticky **inspector** for output and optional tool settings. Generation type is chosen directly under `Generate` in the main sidebar, while the canonical `#generation-mode` control remains the behavioral source of truth.

The main screen must not expose every feature at once. LoRA, Control guidance, Upscale, and advanced settings use progressive disclosure. Image-to-image shows source/edit controls; text-to-image does not. Provider-inapplicable controls disappear rather than becoming visual noise.

At medium widths the inspector moves below or beside the recipe without shrinking the canvas into an unusable strip. At narrow widths the workspace becomes one column and the existing bottom navigation remains usable. No two-dimensional page scrolling is introduced.

## Elevation & Depth

Use tonal surfaces and 1px borders as the primary grouping language. The result canvas may use the existing soft shadow, but nested cards should not each add independent elevation. Sticky desktop surfaces must remain visually attached to the workbench rather than appearing as floating glass panels.

## Shapes

Keep the existing 8–12px radius language. Buttons and inputs use the smaller radius; major workspace surfaces use the larger radius. Mode choices in the sidebar are navigation rows with a small active rail, not pills.

## Components

### Foundational visual states

Every interactive element needs default, hover, focus-visible, active, disabled/busy, and selected treatment. Hidden provider/mode controls use real `hidden` state and must not be forced visible by layout CSS. Busy states keep button geometry stable.

### Buttons and actions

The orange primary action is reserved for `Generate image` and similarly committed actions. Secondary actions are neutral. Icon-only actions require accessible names. Hover motion is restrained and never the only state cue.

### Navigation and data display

`Generate` is a parent navigation item. Supported generation types appear directly beneath it as compact child choices such as `Text to image` and `Image to image`. Child choices mirror model capability state and update the canonical mode select rather than owning separate state.

### Forms and overlays

Creative inputs belong in the recipe column; technical tuning belongs in the inspector. File inputs are visually treated as source/reference tools rather than raw browser controls where possible. Krea Image Edit never exposes classic denoise because its provider workflow does not use that semantic.

### Iconography

Use simple line icons only where they improve scanning. Core workflow choices keep text labels; icons do not replace vocabulary such as `Text to image`, `Control guidance`, or `Upscale`.

### Motion

Motion communicates mode changes, panel disclosure, and generation state. Use short fades/slides around 140–220ms with calm easing. Do not animate dimensions during ordinary form entry. `prefers-reduced-motion: reduce` removes non-essential transforms and animations.

### Content and data visualization

Use plain task language: `Source image`, `Reference image`, `Edit instruction`, `Generate image`. Explain unavailable actions by model capability rather than backend terminology. Generated output and its dimensions/time/model are the primary evidence in the canvas.

## Do's and Don'ts

- **Do:** let the generated image dominate large screens.
- **Do:** reveal tools in context and keep the main recipe short.
- **Do:** preserve one canonical state for model, mode, generation options, and provider capability.
- **Don't:** turn every feature into another permanently expanded card.
- **Don't:** use decorative AI gradients, glass blur, or constant motion.
- **Don't:** expose controls whose semantics do not apply to the active provider or mode.
