"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { apiFetch, clearToken, getToken } from "@/lib/api";
import type { User } from "@/lib/types";

const nav = [
  { href: "/", label: "Dashboard", symbol: "⌂" },
  { href: "/leads", label: "Leads", symbol: "◎" },
  { href: "/leads/new", label: "New Lead", symbol: "+" },
  { href: "/settings", label: "Settings", symbol: "⚙" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    apiFetch<User>("/auth/me")
      .then(setUser)
      .catch(() => {
        clearToken();
        router.replace("/login");
      })
      .finally(() => setLoading(false));
  }, [router]);

  function logout() {
    clearToken();
    router.push("/login");
  }

  if (loading || !user) {
    return <div className="grid min-h-screen place-items-center text-sm text-slate-500">Loading workspace…</div>;
  }

  return (
    <div className="min-h-screen md:grid md:grid-cols-[230px_1fr]">
      <aside className="border-b border-[#dbe3e0] bg-[#102c24] text-white md:min-h-screen md:border-b-0">
        <div className="flex h-16 items-center gap-3 border-b border-white/10 px-5">
          <div className="grid size-8 place-items-center rounded-lg bg-[#efad45] font-black text-[#102c24]">M</div>
          <div>
            <div className="text-sm font-extrabold leading-tight">Missed Lead</div>
            <div className="text-xs text-emerald-100/70">Rescue</div>
          </div>
        </div>
        <nav aria-label="Main navigation" className="flex gap-1 overflow-auto p-3 md:block md:space-y-1">
          {nav.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex min-w-max items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold ${active ? "bg-white/12 text-white" : "text-emerald-50/70 hover:bg-white/7 hover:text-white"}`}
              >
                <span aria-hidden className="w-4 text-center">{item.symbol}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="min-w-0">
        <header className="flex h-16 items-center justify-end border-b border-[#dbe3e0] bg-white px-4 md:px-8">
          <div className="mr-3 text-right">
            <p className="text-sm font-bold">{user.name}</p>
            <p className="text-xs text-slate-500">{user.email}</p>
          </div>
          <button onClick={logout} className="btn btn-secondary text-xs">Log out</button>
        </header>
        <main className="mx-auto max-w-[1400px] p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
