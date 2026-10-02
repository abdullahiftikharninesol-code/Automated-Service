export function AuthFrame({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return <main className="grid min-h-screen place-items-center bg-[#eef3f1] p-4"><div className="w-full max-w-md">
    <div className="mb-6 flex items-center justify-center gap-3"><div className="grid size-10 place-items-center rounded-xl bg-[#116149] text-lg font-black text-white">M</div><div><p className="font-extrabold leading-tight">Missed Lead Rescue</p><p className="text-xs text-slate-500">For HVAC teams</p></div></div>
    <div className="card p-6 md:p-8"><h1 className="text-2xl font-extrabold">{title}</h1><p className="mb-6 mt-1 text-sm text-slate-500">{subtitle}</p>{children}</div>
  </div></main>;
}

export function AuthField({ label, name, type = "text", defaultValue }: { label: string; name: string; type?: string; defaultValue?: string }) {
  return <label className="block"><span className="label">{label}</span><input required className="field" name={name} type={type} defaultValue={defaultValue} /></label>;
}
