// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderHook, waitFor } from "@testing-library/react";

import { useAsyncData } from "./useAsyncData";

afterEach(cleanup);

/** Elle çözülebilen ertelenmiş promise. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("useAsyncData", () => {
  it("başarılı okumada data doldurur, loading kapanır", async () => {
    const { result } = renderHook(() => useAsyncData(() => Promise.resolve(42), []));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBe(42);
    expect(result.current.error).toBeNull();
  });

  it("deps değişince eski (geç çözülen) sonucu uygulamaz (stale guard)", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    let call = 0;

    const { result, rerender } = renderHook(
      ({ dep }: { dep: number }) =>
        useAsyncData(() => {
          call += 1;
          return call === 1 ? first.promise : second.promise;
        }, [dep]),
      { initialProps: { dep: 1 } },
    );

    // İkinci deps ile yeniden çalıştır — ilk istek hâlâ beklemede.
    rerender({ dep: 2 });

    // Önce ikinci (güncel) isteği çöz, sonra eski isteği geç çöz.
    second.resolve("güncel");
    await waitFor(() => expect(result.current.data).toBe("güncel"));

    first.resolve("bayat");
    // Kısa bir bekleme sonrası bayat veri UYGULANMAMALI.
    await new Promise((r) => setTimeout(r, 10));
    expect(result.current.data).toBe("güncel");
  });

  it("deps değişince önceki entity verisini hemen temizler", async () => {
    const second = deferred<string>();
    const { result, rerender } = renderHook(
      ({ entityId }: { entityId: string }) =>
        useAsyncData(
          () => entityId === "e-1" ? Promise.resolve("birinci") : second.promise,
          [entityId],
        ),
      { initialProps: { entityId: "e-1" } },
    );
    await waitFor(() => expect(result.current.data).toBe("birinci"));

    rerender({ entityId: "e-2" });

    await waitFor(() => expect(result.current.loading).toBe(true));
    expect(result.current.data).toBeNull();
    second.resolve("ikinci");
    await waitFor(() => expect(result.current.data).toBe("ikinci"));
  });

  it("disabled iken istek başlatmaz", async () => {
    const fetcher = vi.fn(() => Promise.resolve(1));
    const { result } = renderHook(() => useAsyncData(fetcher, [], false));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetcher).not.toHaveBeenCalled();
    expect(result.current.data).toBeNull();
  });
});
