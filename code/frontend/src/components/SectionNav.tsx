import { NavLink } from "react-router-dom";

export interface SectionNavItem {
  slug: string;
  label: string;
  badge?: "action" | "waiting" | "done";
  muted?: boolean;
}

const BADGE_LABEL = { action: "Aksiyon", waiting: "Bekliyor", done: "Tamam" } as const;

/**
 * İşlem detayının bölüm gezinmesi. Bölümler gerçek rotalardır → ARIA tab'ları
 * değil, `aria-current="page"` işaretli gerçek linkler (master §10).
 */
export function SectionNav({
  sections,
  basePath,
}: {
  sections: SectionNavItem[];
  basePath: string;
}) {
  return (
    <nav aria-label="İşlem bölümleri" className="flex flex-wrap gap-2 border-b border-border pb-3">
      {sections.map((section) => (
        <NavLink
          key={section.slug}
          to={`${basePath}/${section.slug}`}
          className={({ isActive }) =>
            [
              "inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold transition",
              isActive
                ? "bg-primary text-white shadow-sm"
                : section.muted ? "text-muted/70 hover:bg-primary-soft hover:text-primary" : "text-body hover:bg-primary-soft hover:text-primary",
            ].join(" ")
          }
        >
          {section.label}
          {section.badge ? <span className={isBadgeOnPrimary(section.badge) + " rounded-full px-2 py-0.5 text-[0.65rem] font-bold uppercase tracking-wide"}>{BADGE_LABEL[section.badge]}</span> : null}
        </NavLink>
      ))}
    </nav>
  );
}

function isBadgeOnPrimary(badge: NonNullable<SectionNavItem["badge"]>): string {
  if (badge === "done") return "bg-positive-soft text-positive";
  if (badge === "action") return "bg-primary-soft text-primary";
  return "bg-subtle text-muted";
}
