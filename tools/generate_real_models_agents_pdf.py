from __future__ import annotations

import json
from pathlib import Path
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT = ROOT / "output" / "pdf" / "real_models_and_agents_evidence.pdf"
M1 = ROOT / "models" / "cataract_grade_multidata_real"
M2 = ROOT / "models" / "clinical_fusion_catscreen_real"

navy = colors.HexColor("#16324F")
teal = colors.HexColor("#147A70")
coral = colors.HexColor("#E96F51")
ink = colors.HexColor("#23353D")
muted = colors.HexColor("#5D6D74")
pale = colors.HexColor("#EEF7F5")
warm = colors.HexColor("#FFF4EE")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="Kicker", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=teal, spaceAfter=4, tracking=1.1))
styles.add(ParagraphStyle(name="Title2", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=23, leading=27, textColor=navy, alignment=TA_LEFT, spaceAfter=8))
styles.add(ParagraphStyle(name="Deck", parent=styles["Normal"], fontSize=10, leading=15, textColor=muted, spaceAfter=12))
styles.add(ParagraphStyle(name="H2x", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=navy, spaceBefore=7, spaceAfter=5))
styles.add(ParagraphStyle(name="Bodyx", parent=styles["BodyText"], fontSize=8.7, leading=12.5, textColor=ink, spaceAfter=6))
styles.add(ParagraphStyle(name="Smallx", parent=styles["BodyText"], fontSize=7.2, leading=10, textColor=muted, spaceAfter=4))
styles.add(ParagraphStyle(name="White", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.white))


def metric_cell(label: str, value: str, note: str):
    return [Paragraph(label.upper(), styles["Smallx"]), Paragraph(value, ParagraphStyle("metric", parent=styles["Title2"], fontSize=17, leading=19, textColor=navy, spaceAfter=1)), Paragraph(note, styles["Smallx"])]


def metric_row(items):
    table = Table([items], colWidths=[44 * mm] * len(items), hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), pale), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#C9DED9")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D5E7E3")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def figure_pair(left: Path, right: Path, captions: tuple[str, str]):
    images = []
    for path in (left, right):
        im = Image(str(path), width=86 * mm, height=50 * mm)
        im.hAlign = "CENTER"; images.append(im)
    table = Table([images, [Paragraph(captions[0], styles["Smallx"]), Paragraph(captions[1], styles["Smallx"])]], colWidths=[91 * mm, 91 * mm])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (-1, 0), "CENTER"), ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    return table


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#DDE7E8")); canvas.line(18 * mm, 14 * mm, 192 * mm, 14 * mm)
    canvas.setFont("Helvetica", 7); canvas.setFillColor(muted)
    canvas.drawString(18 * mm, 9 * mm, "CataTriage-AI | Research evidence | Not for patient care")
    canvas.drawRightString(192 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def main():
    m1 = json.loads((M1 / "metrics.json").read_text(encoding="utf-8"))
    m2 = json.loads((M2 / "metrics.json").read_text(encoding="utf-8"))
    if m1.get('model_version')=='v2':
        from tools.generate_tuned_evidence_pdf import main as tuned_report
        return tuned_report()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(OUT), pagesize=A4, rightMargin=17 * mm, leftMargin=17 * mm, topMargin=16 * mm, bottomMargin=18 * mm, title="CataTriage-AI Real Models and Four Agents Evidence")
    story = []

    story += [Paragraph("REAL-DATA MODEL EVIDENCE", styles["Kicker"]), Paragraph("Two models, one honest boundary", styles["Title2"]), Paragraph("This short report explains what was trained on the local RTX 2050, what the held-out results mean, and how the four safety agents control the web workflow. The results are real research measurements, but they are not clinical validation.", styles["Deck"])]
    warning = Table([[Paragraph("RESEARCH ONLY", styles["White"]), Paragraph("No output may be used as a diagnosis, treatment decision, urgency score, or automatic queue priority. A doctor must review every case.", styles["Bodyx"])]], colWidths=[34 * mm, 146 * mm])
    warning.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), coral), ("BACKGROUND", (1, 0), (1, 0), warm), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [warning, Spacer(1, 7), Paragraph("Model 01 - multi-data cataract grade estimator", styles["H2x"]), Paragraph("Data: 1,986 usable de-identified participants from the Taizhou Eye Study. Inputs include age, sex code, visual acuity, eye-history fields, outdoor exposure, and related non-grade information. The target is the highest available bilateral cataract grade grouped into grade 0, 1, 2, or 3+.", styles["Bodyx"])]
    t1 = m1["metrics"]["test"]
    story += [metric_row([
        metric_cell("Exact accuracy", f"{t1['accuracy']*100:.1f}%", "160/298 were exact"),
        metric_cell("Macro-F1", f"{t1['macro_f1']*100:.1f}%", "classes weighted equally"),
        metric_cell("Weighted kappa", f"{t1['quadratic_weighted_kappa']:.3f}", "ordinal agreement"),
        metric_cell("Grade MAE", f"{t1['grade_mae']:.3f}", "lower is better"),
    ]), Spacer(1, 6), figure_pair(M1 / "training_curves.png", M1 / "test_confusion_matrix.png", ("Training and validation history.", "Held-out 298-person test confusion matrix.")), Paragraph("Split and leakage control", styles["H2x"]), Paragraph("The split was stratified at participant level: 1,390 train, 298 validation, and 298 test. Scaling and missing-value imputation were learned from the training split only. Direct cataract flags, lens status, cataract history/surgery, cataract type, and every grade column were removed from the inputs.", styles["Bodyx"]), Paragraph("Meaning: the model shows useful ordinal signal, but exact four-level grading is difficult from non-imaging information. The 53.7% test accuracy must not be described as doctor-level performance.", styles["Bodyx"]), PageBreak()]

    story += [Paragraph("REAL SLIT-LAMP BENCHMARK", styles["Kicker"]), Paragraph("Model 02 - image-context fusion CNN", styles["Title2"]), Paragraph("Data: the official CatScreen public sample, containing 200 real slit-lamp images with fixed train, validation, and test files. The model uses an ImageNet-pretrained MobileNetV3-Small image encoder plus a structured branch for eye side, reflection, image quality, and illumination type.", styles["Deck"])]
    t2 = m2["metrics"]["test"]
    story += [metric_row([
        metric_cell("Accuracy", f"{t2['accuracy']*100:.1f}%", "21/40 images correct"),
        metric_cell("Balanced accuracy", f"{t2['balanced_accuracy']*100:.1f}%", "mean class recall"),
        metric_cell("Macro-F1", f"{t2['macro_f1']*100:.1f}%", "three classes equally weighted"),
        metric_cell("Test people", str(m2["participant_counts"]["test"]), "40 images"),
    ]), Spacer(1, 6), figure_pair(M2 / "training_curves.png", M2 / "test_confusion_matrix.png", ("GPU training with validation selection.", "Official test: normal, cataract, other.")), Paragraph("What worked and what did not", styles["H2x"])]
    recalls = t2["per_class_recall"]
    detail = [["Class", "Test recall", "Plain meaning"], ["Normal", f"{recalls['normal']*100:.1f}%", "Weak: most normal images were missed"], ["Cataract", f"{recalls['cataract']*100:.1f}%", "Moderate signal in this small sample"], ["Other", f"{recalls['other']*100:.1f}%", "All five test examples were found"]]
    table = Table(detail, colWidths=[35 * mm, 35 * mm, 110 * mm])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#CFDADD")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F9F9")]), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [table, Spacer(1, 6), Paragraph("Important limit: the sample has only 140 train, 20 validation, and 40 test images. Participant IDs do not overlap between splits, but the test is too small for clinical claims. The public snapshot also omits the full patient metadata described for the licensed release, so this is image plus acquisition-context fusion, not a complete clinical-data fusion study.", styles["Bodyx"]), Paragraph("The safety agent flags the weak normal recall and the small sample on every result. A low score is never treated as reassurance.", styles["Bodyx"]), PageBreak()]

    story += [Paragraph("AUDITABLE AI WORKFLOW", styles["Kicker"]), Paragraph("Four agents with one clinical boundary", styles["Title2"]), Paragraph("The agents are deterministic software stages, not independent doctors. Each stage records what it did so a reviewer can follow the evidence path.", styles["Deck"])]
    agents = [
        ("01", "Data preprocessing", "Checks image type, size, brightness, contrast, required fields, and declared modality. Bad or unsupported input stops safely."),
        ("02", "Model inference", "Runs only the matching locked model and returns class scores. It never creates an urgency tier."),
        ("03", "Safety and rule validation", "Flags low confidence, public-sample limits, unsupported modalities, and known performance gaps. It always requires doctor review."),
        ("04", "Explanation and reporting", "Turns the technical result into plain language, preserves limitations, and writes the audit record without giving treatment advice."),
    ]
    agent_rows = []
    for number, title, body in agents:
        agent_rows.append([Paragraph(number, ParagraphStyle("num", parent=styles["Title2"], fontSize=18, textColor=coral)), Paragraph(f"<b>{title}</b><br/>{body}", styles["Bodyx"])])
    at = Table(agent_rows, colWidths=[20 * mm, 160 * mm])
    at.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F7FAFA")), ("INNERGRID", (0, 0), (-1, -1), .4, colors.HexColor("#D8E3E4")), ("BOX", (0, 0), (-1, -1), .5, colors.HexColor("#C8D8DA")), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [at, Spacer(1, 8), Paragraph("Data provenance", styles["H2x"]), Paragraph("Model 01 source: Tang et al., Taizhou Eye Study phase 1, Dryad DOI 10.5061/dryad.gt410 (CC0 1.0). Model 02 source: CatScreen official public sample and the CatScreen TMLR paper. The full CatScreen release requires an institutional, non-commercial research license; no access control was bypassed.", styles["Bodyx"]), Paragraph("Sources: https://datadryad.org/dataset/doi:10.5061/dryad.gt410 | https://www.iab-rubric.org/resources/healthcare-datasets/catscreen | https://openreview.net/pdf?id=cF7tSNAVQ6", styles["Smallx"]), Paragraph("Bottom line", styles["H2x"]), Paragraph("The web app now runs two real-data research models and keeps the former synthetic models in a clearly separated simulation area. The honest evidence says the pipelines work, but the results are not accurate enough or broadly validated enough for patient care. The doctor remains the only source of clinical interpretation and workflow priority.", styles["Bodyx"])]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUT)


if __name__ == "__main__":
    main()
