import { describe, expect, it } from "vitest";
import { buildFinalFrameContent, buildPreviewHeadContent, pinColorScheme } from "../frame-content";

// Appomax: a sandboxed frame reads the OS colour scheme; the widget must follow the app's theme instead.
describe("pinColorScheme", () => {
  const css = "@media (prefers-color-scheme: dark) { a { color: white } } @media screen and (prefers-color-scheme:light) { b { color: black } }";
  it("light app: dark rules never apply, light rules always do", () => {
    expect(pinColorScheme(css, false)).toBe("@media (max-width: -1px) { a { color: white } } @media screen and (min-width: 0px) { b { color: black } }");
  });
  it("dark app: the opposite", () => {
    expect(pinColorScheme(css, true)).toBe("@media (min-width: 0px) { a { color: white } } @media screen and (max-width: -1px) { b { color: black } }");
  });
  it("the final document and the preview head carry no OS colour-scheme query, and set color-scheme", () => {
    const doc = buildFinalFrameContent(`<html><head></head><body><style>${css}</style></body></html>`, css, false);
    expect(doc).not.toMatch(/prefers-color-scheme/);
    expect(doc).toContain('<meta name="color-scheme" content="light">');
    const head = buildPreviewHeadContent(css, `<style>${css}</style>`, false);
    expect(head).not.toMatch(/prefers-color-scheme/);
  });
});
