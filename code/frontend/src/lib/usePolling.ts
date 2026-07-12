import { useEffect } from "react";

/**
 * Yalnız `active` iken çalışan koşullu interval yenilemesi. Unmount'ta veya
 * `active` false olduğunda temizlenir. Odak çalmaz (çağıran callback sadece
 * arka planda veri yeniler).
 */
export function usePolling(
  callback: () => void,
  { active, intervalMs }: { active: boolean; intervalMs: number },
): void {
  useEffect(() => {
    if (!active) return;
    const id = setInterval(callback, intervalMs);
    return () => clearInterval(id);
  }, [active, intervalMs, callback]);
}
