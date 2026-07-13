// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import { SectionNav } from "./SectionNav";

afterEach(cleanup);

describe("SectionNav", () => {
  const sections = [
    { slug: "overview", label: "Genel bakış" },
    { slug: "parties", label: "Taraflar" },
  ];

  it("aktif linke aria-current=page verir", () => {
    render(
      <MemoryRouter initialEntries={["/transactions/tx-1/parties"]}>
        <SectionNav sections={sections} basePath="/transactions/tx-1" />
      </MemoryRouter>,
    );
    const active = screen.getByRole("link", { name: "Taraflar" });
    expect(active.getAttribute("aria-current")).toBe("page");
    const inactive = screen.getByRole("link", { name: "Genel bakış" });
    expect(inactive.getAttribute("aria-current")).toBeNull();
  });

  it("nav'a erişilebilir etiket verir", () => {
    render(
      <MemoryRouter initialEntries={["/transactions/tx-1/overview"]}>
        <SectionNav sections={sections} basePath="/transactions/tx-1" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("navigation", { name: "İşlem bölümleri" })).toBeTruthy();
  });

  it("badge ve muted sekmeyi gösterirken linki tıklanabilir bırakır", () => {
    render(<MemoryRouter initialEntries={["/transactions/tx-1/overview"]}><SectionNav sections={[{ slug: "fulfillment", label: "Teslimat", badge: "waiting", muted: true }]} basePath="/transactions/tx-1" /></MemoryRouter>);
    const link = screen.getByRole("link", { name: /Teslimat/ });
    expect(link.getAttribute("href")).toBe("/transactions/tx-1/fulfillment");
    expect(screen.getByText("Bekliyor")).toBeTruthy();
  });
});
