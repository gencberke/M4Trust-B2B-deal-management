// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { lifecycleFor } from "../lib/lifecycle";
import { LifecycleStepper, NextActionCard } from "./LifecycleStepper";
afterEach(cleanup);
describe("LifecycleStepper", () => {
  it("yedi adımı ve aktif adımı render eder", () => { render(<LifecycleStepper lifecycle={lifecycleFor("active", "seller")} />); expect(screen.getAllByRole("listitem")).toHaveLength(7); expect(screen.getByText("Teslimat").previousElementSibling?.getAttribute("aria-current")).toBe("step"); });
  it("rolün aksiyonunu gerçek bölüm linkine bağlar", () => { render(<MemoryRouter><NextActionCard transactionId="tx-1" lifecycle={lifecycleFor("awaiting_review", "reviewer")} role="reviewer" /></MemoryRouter>); expect(screen.getByRole("link", { name: "İnceleme bulgularını çöz" }).getAttribute("href")).toBe("/transactions/tx-1/rules"); });
});
