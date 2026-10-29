package com.catatriage.doctor;

import android.graphics.*;
import android.graphics.pdf.PdfDocument;
import java.io.*;
import java.util.*;
import org.json.*;

final class ReportPdf {
  private final PdfDocument document = new PdfDocument();
  private PdfDocument.Page page;
  private Canvas canvas;
  private final Paint paint = new Paint(3);
  private int y = 0, number = 0;

  private static String str(JSONObject o, String key) {
    String v = o.optString(key, "");
    return v.equals("null") ? "" : v;
  }

  private void next() {
    Paint saved = new Paint(paint);
    if (page != null) {
      footer();
      document.finishPage(page);
    }
    page = document.startPage(new PdfDocument.PageInfo.Builder(595, 842, ++number).create());
    canvas = page.getCanvas();
    canvas.drawColor(Color.WHITE);
    paint.setColor(0xff102b36);
    canvas.drawRect(0, 0, 595, 70, paint);
    paint.setColor(Color.WHITE);
    paint.setTextSize(19);
    paint.setTypeface(Typeface.DEFAULT_BOLD);
    canvas.drawText("CataTriage AI | Doctor report", 36, 43, paint);
    y = 100;
    paint.set(saved);
  }

  private void footer() {
    paint.setColor(0xff546975);
    paint.setTextSize(9);
    paint.setTypeface(Typeface.DEFAULT);
    canvas.drawText(
        "Private clinical record | Research outputs require doctor review | Page " + number,
        36,
        815,
        paint);
  }

  private void line(String value, boolean heading) {
    paint.setTextSize(heading ? 14 : 11);
    paint.setTypeface(heading ? Typeface.DEFAULT_BOLD : Typeface.DEFAULT);
    paint.setColor(heading ? 0xff027a79 : 0xff102b36);
    if (y > 770) next();
    for (String paragraph : value.split("\n", -1)) {
      StringBuilder row = new StringBuilder();
      for (String word : paragraph.split(" ")) {
        if (paint.measureText(row + word) > 520 && row.length() > 0) {
          if (y > 770) next();
          canvas.drawText(row.toString(), 36, y, paint);
          y += 17;
          row.setLength(0);
        }
        row.append(word).append(' ');
      }
      if (y > 770) next();
      canvas.drawText(row.toString(), 36, y, paint);
      y += 17;
    }
    y += heading ? 8 : 5;
  }

  private void section(String title, String value) {
    line(title, true);
    line(value.isEmpty() ? "Not recorded" : value, false);
  }

  static byte[] create(JSONObject data, String doctor) throws Exception {
    ReportPdf pdf = new ReportPdf();
    pdf.next();
    JSONObject patient = data.getJSONObject("patient"), record = data.getJSONObject("case");
    pdf.section(
        str(patient, "full_name"),
        str(record, "case_id")
            + " | Age "
            + str(record, "age")
            + " | "
            + str(record, "modality")
            + "\nDoctor: "
            + doctor
            + "\nGenerated: "
            + new java.text.SimpleDateFormat("yyyy-MM-dd HH:mm z", Locale.ROOT).format(new Date()));
    pdf.section(
        "Contact and medical history",
        str(patient, "phone")
            + "\n"
            + str(patient, "email")
            + "\n"
            + str(patient, "address")
            + "\n"
            + str(patient, "medical_history"));
    pdf.section("Reported symptoms", str(record, "symptoms"));
    pdf.section("Clinical notes", str(record, "notes"));
    JSONObject summary = data.optJSONObject("eye_summary");
    if (summary != null) {
      pdf.section(
          "Current-round eye findings", str(summary, "headline") + "\n" + str(summary, "scope"));
      JSONArray entries = summary.optJSONArray("entries");
      if (entries != null)
        for (int i = 0; i < entries.length(); i++) {
          JSONObject e = entries.getJSONObject(i);
          pdf.section(str(e, "label"), str(e, "status") + "\n" + str(e, "detail"));
        }
    }
    JSONArray images = data.optJSONArray("images");
    if (images != null)
      for (int i = 0; i < images.length(); i++) {
        JSONObject image = images.getJSONObject(i), analysis = image.optJSONObject("analysis");
        if (analysis == null) continue;
        pdf.section(
            "Image " + image.optInt("id") + " | " + str(image, "eye_side"),
            "Recorded: "
                + str(image, "created_at")
                + "\nStatus: "
                + str(analysis, "status")
                + "\nResearch class: "
                + str(analysis, "top_class")
                + "\nModel confidence: "
                + String.format(Locale.ROOT, "%.1f%%", analysis.optDouble("confidence", 0) * 100)
                + "\n"
                + str(analysis, "reason"));
        JSONArray agents = analysis.optJSONArray("agent_workflow");
        if (agents != null)
          for (int j = 0; j < agents.length(); j++) {
            JSONObject agent = agents.getJSONObject(j);
            pdf.section(str(agent, "agent"), str(agent, "status") + " | " + str(agent, "summary"));
          }
      }
    pdf.section(
        "Independent doctor review",
        str(record, "approved_tier")
            + "\nDecision: "
            + str(record, "review_state")
            + "\nReviewed by: "
            + str(record, "approved_by")
            + "\nReason: "
            + str(record, "approval_reason"));
    JSONObject surgery = data.optJSONObject("surgery");
    if (surgery != null)
      pdf.section(
          "Recorded surgery",
          str(surgery, "surgery_date")
              + " "
              + str(surgery, "slot")
              + "\nStatus: "
              + str(surgery, "status")
              + "\nRationale: "
              + str(surgery, "rationale"));
    pdf.section(
        "Model limitations",
        "Research models have limited held-out performance and are not clinically validated. The"
            + " model confidence is not a measured probability of disease. Image predictions cannot"
            + " establish cataract severity, urgency or a safe waiting time. Eye labels were"
            + " provided by the uploader. The doctor determines diagnosis, priority and"
            + " treatment.");
    pdf.footer();
    pdf.document.finishPage(pdf.page);
    ByteArrayOutputStream out = new ByteArrayOutputStream();
    pdf.document.writeTo(out);
    pdf.document.close();
    return out.toByteArray();
  }
}
