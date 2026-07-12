// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
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
});
