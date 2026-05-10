interface Props {
  status: "safe" | "danger" | null;
  threatCount: number;
  checkedCount: number | null;
}

export function StatusBar({ status, threatCount, checkedCount }: Props) {
  return (
    <div className="h-12 shrink-0 bg-gray-900/95 border-b border-gray-800 px-5 flex items-center justify-between z-20">
      <div className="flex items-center gap-4">
        <h1 className="text-sm font-bold tracking-widest text-white">OPAS</h1>
        <span className="text-[10px] text-gray-500 uppercase tracking-widest hidden sm:inline">
          Orbital Proximity Alert System
        </span>
      </div>
      <div className="flex items-center gap-3">
        {status && (
          <div
            className={`px-3 py-1 rounded text-xs font-bold uppercase tracking-wider ${
              status === "safe"
                ? "bg-green-900/60 text-green-400"
                : "bg-red-900/60 text-red-400"
            }`}
          >
            {status}
            {threatCount > 0 && ` — ${threatCount} risk${threatCount > 1 ? "s" : ""}`}
          </div>
        )}
        {checkedCount !== null && (
          <span className="text-[10px] text-gray-500">
            {checkedCount.toLocaleString()} checked
          </span>
        )}
      </div>
    </div>
  );
}
