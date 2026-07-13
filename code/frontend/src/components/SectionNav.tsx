import { NavLink } from "react-router-dom";

export interface SectionNavItem {
  slug: string;
  label: string;
}

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
    <nav aria-label="İşlem bölümleri" className="flex flex-wrap gap-1 border-b border-border pb-3">
      {sections.map((section) => (
        <NavLink
          key={section.slug}
          to={`${basePath}/${section.slug}`}
          className={({ isActive }) =>
            [
              "rounded-full px-4 py-2 text-sm transition",
              isActive
                ? "bg-primary text-white shadow-sm"
                : "text-body hover:bg-primary-soft hover:text-heading",
            ].join(" ")
          }
        >
          {section.label}
        </NavLink>
      ))}
    </nav>
  );
}
