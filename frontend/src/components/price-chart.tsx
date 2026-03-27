"use client";

import { useEffect, useRef } from "react";
import { createChart, ColorType, AreaSeries, type IChartApi } from "lightweight-charts";
import { useTheme } from "next-themes";

interface PriceChartProps {
  data: { time: string; value: number }[];
  height?: number;
  color?: string;
}

export function PriceChart({ data, height = 200, color }: PriceChartProps) {
  const chartRef = useRef<HTMLDivElement>(null);
  const chartInstance = useRef<IChartApi | null>(null);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return;

    const isDark = resolvedTheme === "dark";

    const chart = createChart(chartRef.current, {
      width: chartRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: isDark ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.4)",
        fontSize: 11,
      },
      grid: {
        vertLines: {
          color: isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)",
        },
        horzLines: {
          color: isDark ? "rgba(255,255,255,0.04)" : "rgba(0,0,0,0.04)",
        },
      },
      rightPriceScale: {
        borderVisible: false,
      },
      timeScale: {
        borderVisible: false,
        timeVisible: true,
      },
      crosshair: {
        horzLine: {
          visible: true,
          labelVisible: true,
        },
        vertLine: {
          visible: true,
          labelVisible: true,
        },
      },
      handleScale: false,
      handleScroll: false,
    });

    const lineColor = color || (isDark ? "#22c55e" : "#16a34a");

    const series = chart.addSeries(AreaSeries, {
      lineColor,
      topColor: lineColor + "30",
      bottomColor: lineColor + "05",
      lineWidth: 2,
    });

    series.setData(data);
    chart.timeScale().fitContent();

    chartInstance.current = chart;

    const resizeObserver = new ResizeObserver(() => {
      if (chartRef.current) {
        chart.applyOptions({ width: chartRef.current.clientWidth });
      }
    });
    resizeObserver.observe(chartRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [data, height, color, resolvedTheme]);

  return <div ref={chartRef} />;
}
