import Link from "next/link";

export default function NotFound() {
  return <main className="grid min-h-screen place-items-center p-5 text-center"><div><p className="text-sm font-bold text-[#116149]">404</p><h1 className="mt-2 text-3xl font-extrabold">Page not found</h1><p className="mt-2 text-slate-500">The page or lead may no longer exist.</p><Link className="btn btn-primary mt-6" href="/">Return to dashboard</Link></div></main>;
}
