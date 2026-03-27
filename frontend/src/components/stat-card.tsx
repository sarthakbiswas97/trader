import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

interface StatCardProps {
  title: string;
  value: string;
  subtitle?: string;
  icon?: LucideIcon;
  trend?: "profit" | "loss" | "neutral";
}

export function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  trend = "neutral",
}: StatCardProps) {
  return (
    <Card>
      <CardContent className="px-4 py-3">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium text-muted-foreground">{title}</p>
          {Icon && (
            <Icon className="h-3.5 w-3.5 text-muted-foreground/60" />
          )}
        </div>
        <p
          className={cn(
            "text-lg font-semibold tracking-tight mt-1",
            trend === "profit" && "text-profit",
            trend === "loss" && "text-loss",
          )}
        >
          {value}
        </p>
        {subtitle && (
          <p className="text-[11px] text-muted-foreground/60 mt-0.5">
            {subtitle}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
