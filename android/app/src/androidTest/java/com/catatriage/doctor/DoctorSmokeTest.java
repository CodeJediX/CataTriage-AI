package com.catatriage.doctor;

import android.app.*;
import android.content.*;
import android.graphics.Bitmap;
import android.test.InstrumentationTestCase;
import android.view.*;
import android.widget.*;
import java.io.*;
import java.lang.reflect.Field;
import org.json.*;

/** Test-only doctor and isolated SQLite server. Never runs against the production API. */
public class DoctorSmokeTest extends InstrumentationTestCase {
  private MainActivity activity;
  private Instrumentation test;

  private void ui(Runnable action) throws Exception {
    test.runOnMainSync(action);
    test.waitForIdleSync();
  }

  private View find(View root, String text) {
    if (text.equals(String.valueOf(root.getContentDescription()))) return root;
    if (root instanceof TextView && text.equals(((TextView) root).getText().toString()))
      return root;
    if (root instanceof ViewGroup) {
      ViewGroup parent = (ViewGroup) root;
      for (int i = 0; i < parent.getChildCount(); i++) {
        View value = find(parent.getChildAt(i), text);
        if (value != null) return value;
      }
    }
    return null;
  }

  private View named(String text) {
    return find(activity.getWindow().getDecorView(), text);
  }

  private View editable(View root,String title) {
    if(root instanceof EditText && title.equals(String.valueOf(root.getContentDescription())))return root;
    if(root instanceof ViewGroup){ViewGroup group=(ViewGroup)root;for(int i=0;i<group.getChildCount();i++){View found=editable(group.getChildAt(i),title);if(found!=null)return found;}}
    return null;
  }

  private View clickable(View root,String title) {
    if(root.isClickable() && (title.equals(String.valueOf(root.getContentDescription())) || root instanceof TextView && title.equals(((TextView)root).getText().toString())))return root;
    if(root instanceof ViewGroup){ViewGroup group=(ViewGroup)root;for(int i=0;i<group.getChildCount();i++){View found=clickable(group.getChildAt(i),title);if(found!=null)return found;}}
    return null;
  }

  private void waitFor(String text) throws Exception {
    long end = System.currentTimeMillis() + 30000;
    while (System.currentTimeMillis() < end) {
      final boolean[] found = {false};
      ui(() -> found[0] = named(text) != null);
      if (found[0]) return;
      Thread.sleep(200);
    }
    fail("Missing UI: " + text);
  }

  private void click(String text) throws Exception {
    waitFor(text);
    ui(
        () -> {
          View target = clickable(activity.getWindow().getDecorView(),text);
          assertNotNull("Clickable control: "+text,target);
          target.performClick();
        });
    Thread.sleep(350);
    test.waitForIdleSync();
  }

  private void screenshot(String name) throws Exception {
    Thread.sleep(300);
    Bitmap image = test.getUiAutomation().takeScreenshot();
    assertNotNull(image);
    try (FileOutputStream out =
        new FileOutputStream(new File(activity.getFilesDir(), name + ".png"))) {
      image.compress(Bitmap.CompressFormat.PNG, 100, out);
    }
    image.recycle();
  }

  public void testDoctorWorkspace() throws Exception {
    test = getInstrumentation();
    assertEquals("http://10.0.2.2:8002", BuildConfig.API_ORIGIN);
    test.getTargetContext().getSharedPreferences("private_session", 0).edit().clear().commit();
    Intent launch =
        new Intent(test.getTargetContext(), MainActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
    activity = (MainActivity) test.startActivitySync(launch);
    waitFor("Doctor username");
    screenshot("signin");
    ui(
        () -> {
          ((EditText) editable(activity.getWindow().getDecorView(),"Doctor username")).setText("dr.maya");
          ((EditText) editable(activity.getWindow().getDecorView(),"Password")).setText("demo-doctor");
        });
    click("Sign in securely  →");
    waitFor("assigned patients");
    screenshot("home");
    click("Patients");
    waitFor("Search patients");
    screenshot("patients");
    click("Open record  →");
    waitFor("Patient overview");
    screenshot("patient");
    click("Images");
    waitFor("Image analysis");
    assertNotNull(named("No images in this round"));
    click("Start a new image upload round");
    waitFor("Start a fresh round");
    assertNotNull(named("Eye side unknown"));
    // The empty-round guard must not issue an intake request or fabricate an image.
    Field selection = MainActivity.class.getDeclaredField("selected");
    selection.setAccessible(true);
    assertTrue(((java.util.Map) selection.get(activity)).isEmpty());
    screenshot("capture");
    click("Patients");
    waitFor("Search patients");
    click("Open record  →");
    waitFor("Patient overview");
    click("Review");
    waitFor("Your clinical decision");
    screenshot("review");
    assertNotNull(named("Suggest a surgery month"));
    assertNull(named("Confirm selected surgery"));
    click("Your profile and settings");
    waitFor("Sign-in username");
    assertNotNull(named("Change profile photograph"));
    assertNotNull(named("Change password securely"));
    screenshot("profile-editor");
    click("Calendar");
    waitFor("A considered schedule");
    screenshot("calendar");
    click("Inbox");
    waitFor("Compose message  +");
    screenshot("inbox");
    click("Compose message  +");
    waitFor("Recipient");
    assertNotNull(named("Subject"));
    assertNotNull(named("Message"));
    // Exercise the actual native PDF renderer, including multi-page text.
    Api api = new Api(test.getTargetContext());
    api.bootstrap();
    JSONObject ws = api.get("/api/mobile/workspace");
    String id = ws.getJSONArray("patients").getJSONObject(0).getString("case_id");
    JSONObject record = api.get("/api/mobile/patients/" + id);
    record.getJSONObject("case").put("notes", "Long-note pagination check. ".repeat(250));
    byte[] pdf = ReportPdf.create(record, "Isolated QA Doctor");
    assertTrue(pdf.length > 1000);
    try (FileOutputStream out =
        new FileOutputStream(new File(activity.getFilesDir(), "qa-report.pdf"))) {
      out.write(pdf);
    }
  }
}
