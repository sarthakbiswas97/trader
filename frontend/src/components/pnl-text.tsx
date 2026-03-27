import { cn } from "@/lib/utils";

interface PnlTextProps {
  value: number;
  percent?: number;
  className?: string;
  showSign?: boolean;
  prefix?: string;
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function PnlText({
  value,
  percent,
  className,
  showSign = true,
  prefix,
}: PnlTextProps) {
  const trend = value > 0 ? "profit" : value < 0 ? "loss" : "neutral";
  const sign = showSign && value > 0 ? "+" : "";

  return (
    <span
      className={cn(
        trend === "profit" && "text-profit",
        trend === "loss" && "text-loss",
        trend === "neutral" && "text-muted-foreground",
        className,
      )}
    >
      {prefix}
      {sign}
      {formatCurrency(value)}
      {percent !== undefined && (
        <span className="text-[11px] ml-1">
          ({sign}
          {percent.toFixed(2)}%)
        </span>
      )}
    </span>
  );
}
