/*
 * panel/components/WbTable.js —— 标准数据表（本地自研，上游无对应）
 *
 * 全面板「列定义 + 行渲染」表格的唯一入口：页面只声明列描述符数组，
 * 尺寸、皮肤类、列构造统一在这里落，后续调密度/换肤/加全局能力只改这一处，
 * 新页面不再重写 ElTable + ElTableColumn 样板。
 *
 *   h(WbTable, { rows, columns, maxHeight, stripe, rowKey })
 *
 * 列描述符（columns 数组元素）：
 *   {
 *     label,                        // 列头文案（必填）
 *     prop?,                        // 字段名；有 render 时仅作语义标注
 *     width?, minWidth?,            // 列宽（操作列建议用 actionWidth(count)）
 *     align?, headerAlign?,         // 对齐；headerAlign 缺省跟随 align
 *     fixed?,                       // 固定列（如操作列 "right"）
 *     sortable?, sortMethod?,       // 排序（数字列用 sortMethod 明确比较，默认按 prop）
 *     render?({ row, $index }),     // 单元格渲染；缺省按 prop 直出文本
 *   }
 *
 * 另导出操作列配套件（账号治理的操作列即范例）：
 *   actionWidth(count) —— 按小号文字按钮个数计算操作列宽（一个 2 字按钮约 44px）
 *   actionRow(buttons) —— 右对齐按钮排（flex + gap 单行，换行仅作超长兜底）
 */
import { h } from "/vendor/vue.mjs";
import { ui } from "./ui.js";

const BTN_W = 44;    // 小号文字按钮（2 字文案）实测宽度
const BTN_GAP = 2;   // actionRow 的按钮间距
const CELL_PAD = 28; // 单元格水平内边距与渲染余量

export function actionWidth(count) {
  return count * BTN_W + Math.max(0, count - 1) * BTN_GAP + CELL_PAD;
}

export function actionRow(buttons) {
  return h("div", {
    style: `display:flex;gap:${BTN_GAP}px;justify-content:flex-end;flex-wrap:wrap;row-gap:2px`,
  }, buttons);
}

export default {
  name: "WbTable",
  props: {
    rows: { type: Array, default: () => [] },
    columns: { type: Array, required: true },
    maxHeight: { type: Number, default: 0 },
    stripe: { type: Boolean, default: false },
    rowKey: { type: String, default: "" },
  },
  render() {
    return h(ui.ElTable, {
      data: this.rows,
      size: "small",
      class: "wb-table",
      maxHeight: this.maxHeight || undefined,
      stripe: this.stripe || undefined,
      rowKey: this.rowKey || undefined,
    }, {
      default: () => this.columns.map((col) => h(ui.ElTableColumn, {
        prop: col.prop || undefined,
        label: col.label,
        width: col.width || undefined,
        minWidth: col.minWidth || undefined,
        align: col.align || undefined,
        headerAlign: col.headerAlign || col.align || undefined,
        fixed: col.fixed || undefined,
        sortable: col.sortable || undefined,
        sortMethod: col.sortMethod || undefined,
      }, {
        default: col.render
          ? (scope) => col.render(scope)
          : (scope) => String(scope.row[col.prop] ?? "—"),
      })),
    });
  },
};
