"use client";

import {
  Activity,
  Bell,
  Bot,
  ChevronRight,
  Database,
  Fingerprint,
  Gauge,
  LifeBuoy,
  LogOut,
  Mail,
  Menu,
  Network,
  Search,
  Users,
  X,
} from "lucide-react";
import {useQuery, useQueryClient} from "@tanstack/react-query";
import Link from "next/link";
import {usePathname, useRouter} from "next/navigation";
import {useEffect, useMemo, useRef, useState, type ReactNode} from "react";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Input} from "@/components/ui/input";
import {request, type CursorPage, type UserSummary} from "@/lib/api";
import type {Session} from "@/lib/session";
import {cn} from "@/lib/utils";
import {formatRelativeTime, RiskBadge} from "@/components/risk-ui";
import {useRiskContext} from "@/components/risk-context";

const NAV_GROUPS = [
  {
    label: "Monitor",
    items: [
      {href: "/", label: "Overview", icon: Gauge, exact: true},
      {href: "/users", label: "Investigations", icon: Users},
      {href: "/alerts", label: "Security alerts", icon: Bell},
      {href: "/mail", label: "Mail telemetry", icon: Mail},
      {href: "/graph", label: "Field data graph", icon: Network},
    ],
  },
  {
    label: "System",
    items: [
      {href: "/operations", label: "Operations", icon: Database},
      {href: "/models", label: "Models", icon: Bot},
    ],
  },
];

function isActive(pathname: string, href: string, exact?: boolean) {
  return exact ? pathname === "/" || pathname === "/overview" : pathname.startsWith(href);
}

function GlobalSearch({session}: {session: Session}) {
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const users = useQuery({
    queryKey: ["users", session.tenant],
    queryFn: () => request<CursorPage<UserSummary>>("/api/v1/users?limit=100", session.token),
    staleTime: 5_000,
  });

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "/" && !event.metaKey && !event.ctrlKey && !event.altKey) {
        const target = event.target as HTMLElement | null;
        if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA") return;
        event.preventDefault();
        setOpen(true);
        requestAnimationFrame(() => input.current?.focus());
      }
      if (event.key === "Escape") {
        setOpen(false);
        setValue("");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const matches = useMemo(() => {
    const needle = value.trim().toLowerCase();
    if (!needle) return [];
    return (users.data?.items ?? [])
      .filter((user) => `${user.display_name} ${user.id}`.toLowerCase().includes(needle))
      .sort((a, b) => b.score - a.score)
      .slice(0, 6);
  }, [users.data?.items, value]);

  function select(userId: string) {
    setOpen(false);
    setValue("");
    router.push(`/users/${userId}`);
  }

  return (
    <div className="relative hidden min-w-0 flex-1 sm:block">
      <label className="relative block max-w-xl">
        <span className="sr-only">Search identities</span>
        <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground"/>
        <Input
          ref={input}
          value={value}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            setValue(event.target.value);
            setOpen(true);
          }}
          className="h-9 border-transparent bg-white/[.035] pr-20 pl-9 shadow-inner shadow-black/10 hover:bg-white/[.05] focus-visible:bg-background"
          placeholder="Search identities"
        />
        <span className="pointer-events-none absolute top-1/2 right-2.5 hidden -translate-y-1/2 items-center gap-1 rounded border border-border bg-black/15 px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground lg:flex">
          /
        </span>
      </label>
      {open && value.trim() ? (
        <div className="absolute top-11 left-0 z-50 w-full max-w-xl overflow-hidden rounded-xl border bg-popover shadow-2xl shadow-black/40">
          <div className="flex items-center justify-between border-b px-3 py-2 text-[10px] uppercase tracking-[.15em] text-muted-foreground">
            <span>Identity results</span>
            <button onClick={() => setOpen(false)} aria-label="Close search"><X className="size-3.5"/></button>
          </div>
          {matches.map((user) => (
            <button
              key={user.id}
              onClick={() => select(user.id)}
              className="flex w-full items-center gap-3 border-b px-3 py-3 text-left transition-colors last:border-b-0 hover:bg-accent focus-visible:bg-accent"
            >
              <span className="grid size-8 place-items-center rounded-lg bg-primary/10 font-mono text-[10px] text-primary ring-1 ring-primary/15">
                {user.display_name.split(" ").map((part) => part[0]).join("").slice(0, 2)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium">{user.display_name}</span>
                <span className="mono-data mt-0.5 block text-[10px] text-muted-foreground">{user.id}</span>
              </span>
              <span className="mono-data text-sm font-semibold">{user.score}</span>
              <RiskBadge level={user.level}/>
            </button>
          ))}
          {!matches.length ? <p className="px-4 py-6 text-center text-xs text-muted-foreground">No identity matches “{value}”.</p> : null}
        </div>
      ) : null}
    </div>
  );
}

export function AppShell({
  session,
  onLogout,
  children,
}: {
  session: Session;
  onLogout: () => void;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const {connection, model, summary, stale} = useRiskContext();
  const [mobileOpen, setMobileOpen] = useState(false);

  function logout() {
    queryClient.clear();
    onLogout();
  }

  const nav = (
    <>
      <div className="flex h-16 items-center justify-between px-4 md:h-auto md:px-5 md:pt-5">
        <Link href="/" className="group flex items-center gap-3 rounded-lg focus-visible:ring-2 focus-visible:ring-ring">
          <span className="brand-mark"><Activity className="size-4" strokeWidth={2}/></span>
          <span className="sidebar-label hidden xl:block">
            <span className="block text-sm font-semibold tracking-[-.025em]">Risk Command</span>
            <span className="mt-0.5 block text-[9px] uppercase tracking-[.16em] text-muted-foreground">M365 intelligence</span>
          </span>
        </Link>
        <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setMobileOpen(false)} aria-label="Close navigation"><X/></Button>
      </div>
      <nav className="scrollbar-none flex-1 overflow-y-auto px-3 py-5 md:mt-5 md:py-0 xl:px-4" aria-label="Primary navigation">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="mb-6">
            <p className="sidebar-label mb-2 hidden px-2 text-[9px] font-semibold uppercase tracking-[.18em] text-muted-foreground/70 xl:block">{group.label}</p>
            <div className="grid gap-1">
              {group.items.map(({href, label, icon: Icon, exact}) => {
                const active = isActive(pathname, href, exact);
                return (
                  <Link
                    key={href}
                    href={href}
                    onClick={() => setMobileOpen(false)}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "nav-item group",
                      active ? "nav-item-active" : "text-muted-foreground hover:bg-white/[.035] hover:text-foreground",
                    )}
                    title={label}
                  >
                    <Icon className="size-4 shrink-0" strokeWidth={active ? 2 : 1.65}/>
                    <span className="sidebar-label hidden xl:inline">{label}</span>
                    {active ? <ChevronRight className="sidebar-label ml-auto hidden size-3.5 xl:block"/> : null}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
      <div className="border-t px-3 py-4 xl:px-4">
        <div className="sidebar-label hidden rounded-xl bg-white/[.025] p-3 ring-1 ring-border xl:block">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-2 text-[10px] font-medium">
              <span className={cn("size-1.5 rounded-full", connection?.status === "connected" ? "status-pulse bg-primary" : "bg-amber-300")}/>
              {connection?.mode === "real" ? "Microsoft Graph" : "Mock Graph"}
            </span>
            <span className="mono-data text-[9px] text-muted-foreground">
              {connection?.status === "connected" && !connection.updated_at
                ? "live"
                : formatRelativeTime(connection?.updated_at)}
            </span>
          </div>
          <p className="mt-2 truncate text-[10px] capitalize text-muted-foreground">{connection?.status ?? "Checking connection"}</p>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-primary/10 text-[10px] font-semibold text-primary ring-1 ring-primary/15">
            {session.tenant.split(" ").map((word) => word[0]).join("").slice(0, 2)}
          </span>
          <span className="sidebar-label hidden min-w-0 flex-1 xl:block">
            <span className="block truncate text-[11px] font-medium">{session.tenant}</span>
            <span className="mt-0.5 block text-[9px] capitalize text-muted-foreground">{session.role}</span>
          </span>
          <Button variant="ghost" size="icon-sm" onClick={logout} className="ml-auto text-muted-foreground" aria-label="Sign out"><LogOut/></Button>
        </div>
      </div>
    </>
  );

  return (
    <div className="min-h-screen md:grid md:grid-cols-[72px_minmax(0,1fr)] xl:grid-cols-[236px_minmax(0,1fr)]">
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <aside className="sidebar-shell sticky top-0 z-40 hidden h-screen min-h-0 flex-col md:flex">{nav}</aside>
      {mobileOpen ? (
        <div className="fixed inset-0 z-50 md:hidden">
          <button className="absolute inset-0 bg-black/70 backdrop-blur-sm" aria-label="Close navigation" onClick={() => setMobileOpen(false)}/>
          <aside className="mobile-sidebar sidebar-shell relative flex h-full w-[280px] flex-col shadow-2xl">{nav}</aside>
        </div>
      ) : null}

      <div className="min-w-0">
        <header className="topbar-shell">
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu/></Button>
          <GlobalSearch session={session}/>
          <div className="ml-auto flex items-center gap-2">
            <div className="hidden items-center gap-2 rounded-lg border bg-black/10 px-2.5 py-1.5 lg:flex">
              <span className={cn("size-1.5 rounded-full", stale ? "bg-amber-300" : "status-pulse bg-primary")}/>
              <span className="text-[10px]">{stale ? "Data freshness warning" : "Live monitoring"}</span>
            </div>
            <Badge variant="outline" className={cn("hidden h-7 sm:inline-flex", model?.approved ? "border-primary/20 text-primary" : "border-amber-400/20 text-amber-100")}>
              <Fingerprint className="size-3"/>
              <span className="mono-data text-[9px]">{model?.version ?? "model"} · {model?.approved ? "approved" : "demo"}</span>
            </Badge>
            <Button asChild variant="ghost" size="icon" className="relative">
              <Link href="/users" aria-label="Open urgent investigations">
                <Bell className="size-4"/>
                {(summary?.critical ?? 0) > 0 ? <span className="absolute top-1.5 right-1.5 size-1.5 rounded-full bg-rose-400"/> : null}
              </Link>
            </Button>
            <Button asChild variant="ghost" size="icon">
              <Link href="/operations" aria-label="Open operations">
                <Activity className="size-4"/>
              </Link>
            </Button>
          </div>
        </header>
        <main id="main-content" className="min-w-0 px-4 pt-6 pb-14 sm:px-6 lg:px-8 xl:px-10">
          <div className="mx-auto max-w-[1540px]">{children}</div>
        </main>
        <footer className="mx-4 flex flex-col gap-2 border-t py-5 text-[10px] text-muted-foreground sm:mx-6 sm:flex-row sm:items-center sm:justify-between lg:mx-8 xl:mx-10">
          <span>Privacy-safe metadata only · tenant-isolated by design</span>
          <div className="flex items-center gap-4">
            <Link href="/operations" className="hover:text-foreground">System status</Link>
            <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer" className="hover:text-foreground">API docs</a>
            <span className="flex items-center gap-1"><LifeBuoy className="size-3"/>Offline demo</span>
          </div>
        </footer>
      </div>
    </div>
  );
}
