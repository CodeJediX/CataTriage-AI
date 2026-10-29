package com.catatriage.doctor;

import android.app.*;
import android.content.*;
import android.graphics.*;
import android.graphics.drawable.*;
import android.net.Uri;
import android.os.*;
import android.provider.*;
import android.text.*;
import android.text.InputType;
import android.view.*;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import java.io.*;
import java.text.*;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;

/** Native doctor workspace. No WebView, no seeded images and no embedded login. */
public class MainActivity extends Activity {
  private static final int INK = 0xff102b36,
      TEAL = 0xff027a79,
      PAPER = 0xfff4f6f3,
      MUTED = 0xff546975,
      LINE = 0xffdce5e2,
      WHITE = 0xffffffff;
  private Api api;
  private JSONObject me = new JSONObject(),
      workspace = new JSONObject(),
      patientData = new JSONObject();
  private LinearLayout shell, content, nav;
  private FrameLayout stage;
  private LinearLayout busy;
  private TextView busyLabel;
  private final ExecutorService worker = Executors.newSingleThreadExecutor();
  private String tab = "Home", currentCase = "", caseTab = "Overview", mailbox = "inbox";
  private int generation = 0;
  private final LinkedHashMap<String, Uri> selected = new LinkedHashMap<>();
  private String pendingSide = "Left";
  private Uri cameraUri;
  private LinearLayout imageOptions;
  private byte[] pdfBytes;

  interface Job {
    JSONObject run() throws Exception;
  }

  interface Done {
    void run(JSONObject result) throws Exception;
  }

  @Override
  public void onCreate(Bundle state) {
    super.onCreate(state);
    api = new Api(this);
    getWindow().setStatusBarColor(INK);
    getWindow().setNavigationBarColor(INK);
    // The native layouts reserve both system bar insets, including Android 15 edge-to-edge.
    if (Build.VERSION.SDK_INT >= 30) getWindow().setDecorFitsSystemWindows(false);
    splash();
    run(
        "Connecting to your workspace…",
        () -> {
          api.bootstrap();
          return api.get("/api/mobile/me");
        },
        r -> {
          me = r;
          if (r.optBoolean("must_change")) password();
          else refresh("Home");
        },
        true);
  }

  @Override
  protected void onDestroy() {
    worker.shutdownNow();
    super.onDestroy();
  }

  private int d(float n) {
    return Math.round(n * getResources().getDisplayMetrics().density);
  }

  private String s(JSONObject o, String key) {
    String value = o.optString(key, "");
    return "null".equals(value) ? "" : value;
  }

  private JSONArray a(JSONObject o, String key) {
    JSONArray v = o.optJSONArray(key);
    return v == null ? new JSONArray() : v;
  }

  private JSONObject o(JSONObject x, String key) {
    JSONObject v = x.optJSONObject(key);
    return v == null ? new JSONObject() : v;
  }

  private JSONObject at(JSONArray list, int i) {
    JSONObject v = list.optJSONObject(i);
    return v == null ? new JSONObject() : v;
  }

  private String text(EditText input) {
    return input.getText().toString().trim();
  }

  private String nice(String value) {
    return value.replace('_', ' ');
  }

  private GradientDrawable background(int color, int radius) {
    GradientDrawable shape = new GradientDrawable();
    shape.setColor(color);
    shape.setCornerRadius(d(radius));
    return shape;
  }

  private TextView label(String text, int size, int color, boolean bold) {
    TextView v = new TextView(this);
    v.setText(text);
    v.setTextSize(size);
    v.setTextColor(color);
    v.setLineSpacing(d(3), 1);
    if (bold) v.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
    return v;
  }

  private void gap(LinearLayout parent, int height) {
    View space = new View(this);
    parent.addView(space, new LinearLayout.LayoutParams(1, d(height)));
  }

  private void add(LinearLayout parent, View view) {
    parent.addView(view, new LinearLayout.LayoutParams(-1, -2));
  }

  private void copy(String value) {
    ((android.content.ClipboardManager) getSystemService(CLIPBOARD_SERVICE))
        .setPrimaryClip(ClipData.newPlainText("CataTriage", value));
    Toast.makeText(this, "Copied", Toast.LENGTH_SHORT).show();
  }

  private void frame(String eyebrow, String title, boolean back, boolean withNav) {
    generation++;
    shell = new LinearLayout(this);
    shell.setOrientation(LinearLayout.VERTICAL);
    shell.setBackgroundColor(PAPER);
    shell.setOnApplyWindowInsetsListener(
        (v, insets) -> {
          if (Build.VERSION.SDK_INT >= 30) {
            android.graphics.Insets bars =
                insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
            v.setPadding(bars.left, bars.top, bars.right, bars.bottom);
          } else
            v.setPadding(
                insets.getSystemWindowInsetLeft(),
                insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(),
                insets.getSystemWindowInsetBottom());
          return insets;
        });
    shell.setBackgroundColor(INK);
    LinearLayout header = new LinearLayout(this);
    header.setGravity(Gravity.CENTER_VERTICAL);
    header.setPadding(d(20), d(14), d(20), d(16));
    if (back) {
      TextView arrow = label("‹", 36, 0xff6de3d7, false);
      arrow.setContentDescription("Back");
      arrow.setGravity(Gravity.CENTER);
      header.addView(arrow, new LinearLayout.LayoutParams(d(44), d(52)));
      arrow.setOnClickListener(v -> goBack());
    }
    LinearLayout titles = new LinearLayout(this);
    titles.setOrientation(LinearLayout.VERTICAL);
    add(titles, label(eyebrow.toUpperCase(Locale.ROOT), 10, 0xff92c8cb, true));
    TextView name = label(title, 24, WHITE, false);
    name.setTypeface(Typeface.create("serif", Typeface.NORMAL));
    add(titles, name);
    header.addView(titles, new LinearLayout.LayoutParams(0, -2, 1));
    if (withNav) {
      TextView avatar = label(initials(s(me, "name")), 14, INK, true);
      avatar.setGravity(Gravity.CENTER);
      avatar.setBackground(background(0xffa4ece0, 22));
      header.addView(avatar, new LinearLayout.LayoutParams(d(44), d(44)));
      avatar.setContentDescription("Your profile and settings");
      avatar.setOnClickListener(
          v -> {
            if (!busy.isShown()) profile();
          });
    }
    add(shell, header);
    stage = new FrameLayout(this);
    stage.setBackgroundColor(PAPER);
    shell.addView(stage, new LinearLayout.LayoutParams(-1, 0, 1));
    ScrollView scroll = new ScrollView(this);
    scroll.setFillViewport(true);
    content = new LinearLayout(this);
    content.setOrientation(LinearLayout.VERTICAL);
    content.setPadding(d(20), d(22), d(20), d(28));
    scroll.addView(content);
    stage.addView(scroll, new FrameLayout.LayoutParams(-1, -1));
    busy = new LinearLayout(this);
    busy.setOrientation(LinearLayout.VERTICAL);
    busy.setGravity(Gravity.CENTER);
    busy.setPadding(d(30), d(20), d(30), d(20));
    busy.setBackgroundColor(0xf5f4f6f3);
    busy.setClickable(true);
    ProgressBar progress = new ProgressBar(this);
    busy.addView(progress, new LinearLayout.LayoutParams(d(44), d(44)));
    gap(busy, 20);
    busyLabel = label("Loading…", 16, INK, true);
    busyLabel.setGravity(Gravity.CENTER);
    add(busy, busyLabel);
    busy.setVisibility(View.GONE);
    stage.addView(busy, new FrameLayout.LayoutParams(-1, -1));
    if (withNav) {
      nav = new LinearLayout(this);
      nav.setBackgroundColor(WHITE);
      nav.setPadding(d(5), d(6), d(5), d(6));
      String[] names = {"Home", "Patients", "Calendar", "Inbox"};
      String[] glyphs = {"⌂", "⊕", "▦", "✉"};
      for (int i = 0; i < names.length; i++) {
        final String dest = names[i];
        TextView n =
            label(glyphs[i] + "\n" + dest, 12, tab.equals(dest) ? TEAL : MUTED, tab.equals(dest));
        n.setGravity(Gravity.CENTER);
        n.setMinHeight(d(58));
        n.setContentDescription(dest);
        if (tab.equals(dest)) n.setBackground(background(0xffe5f4ee, 16));
        nav.addView(n, new LinearLayout.LayoutParams(0, -2, 1));
        n.setOnClickListener(
            v -> {
              if (!busy.isShown()) {
                currentCase = "";
                refresh(dest);
              }
            });
      }
      add(shell, nav);
    }
    setContentView(shell);
    shell.requestApplyInsets();
  }

  private String initials(String name) {
    StringBuilder out = new StringBuilder();
    for (String part : name.replace("Dr.", "").trim().split(" +")) {
      if (!part.isEmpty()) out.append(part.charAt(0));
      if (out.length() == 2) break;
    }
    return out.length() > 0 ? out.toString().toUpperCase(Locale.ROOT) : "DR";
  }

  private void splash() {
    frame("CataTriage AI", "Doctor", false, false);
    gap(content, 35);
    IrisView iris = new IrisView(this);
    content.addView(iris, new LinearLayout.LayoutParams(-1, d(230)));
    heading("Your clinic,\nwithin reach.");
    para("Connecting securely to CataTriage.");
    button(
        content,
        "Try connecting again",
        () ->
            run(
                "Connecting�",
                () -> {
                  api.bootstrap();
                  return api.get("/api/mobile/me");
                },
                r -> {
                  me = r;
                  if (r.optBoolean("must_change")) password();
                  else refresh("Home");
                },
                true),
        true);
    button(content, "Doctor sign in", () -> login(), false);
  }

  private void heading(String value) {
    TextView h = label(value, 32, INK, false);
    h.setTypeface(Typeface.create("serif", Typeface.NORMAL));
    add(content, h);
    gap(content, 12);
  }

  private void para(String value) {
    add(content, label(value, 14, MUTED, false));
    gap(content, 16);
  }

  private void section(String value) {
    gap(content, 18);
    add(content, label(value.toUpperCase(Locale.ROOT), 11, TEAL, true));
    gap(content, 12);
  }

  private LinearLayout card(LinearLayout parent) {
    LinearLayout c = new LinearLayout(this);
    c.setOrientation(LinearLayout.VERTICAL);
    c.setPadding(d(17), d(16), d(17), d(16));
    c.setBackground(background(WHITE, 18));
    LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(-1, -2);
    params.bottomMargin = d(12);
    parent.addView(c, params);
    return c;
  }

  private void info(String title, String value) {
    LinearLayout c = card(content);
    add(c, label(title, 12, TEAL, true));
    gap(c, 5);
    add(c, label(value.isEmpty() ? "Not recorded" : value, 15, INK, false));
  }

  private Button button(LinearLayout parent, String title, Runnable click, boolean primary) {
    Button b = new Button(this);
    b.setText(title);
    b.setAllCaps(false);
    b.setTextSize(14);
    b.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
    b.setTextColor(primary ? WHITE : TEAL);
    b.setBackground(background(primary ? TEAL : 0xffe3efeb, 14));
    b.setMinHeight(d(52));
    LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, d(54));
    lp.topMargin = d(9);
    lp.bottomMargin = d(5);
    parent.addView(b, lp);
    b.setOnClickListener(v -> click.run());
    return b;
  }

  private EditText input(LinearLayout parent, String title, String value, boolean multiline) {
    add(parent, label(title, 12, MUTED, true));
    EditText e = new EditText(this);
    e.setText(value);
    e.setTextSize(15);
    e.setTextColor(INK);
    e.setHintTextColor(MUTED);
    e.setPadding(d(13), d(13), d(13), d(13));
    e.setBackground(background(WHITE, 12));
    e.setSingleLine(!multiline);
    e.setInputType(
        InputType.TYPE_CLASS_TEXT
            | (multiline
                ? InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
                : 0));
    if (multiline) {
      e.setMinLines(3);
      e.setGravity(Gravity.TOP);
    }
    e.setContentDescription(title);
    LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
    lp.topMargin = d(6);
    lp.bottomMargin = d(16);
    parent.addView(e, lp);
    return e;
  }

  private Spinner select(LinearLayout parent, String title, String[] choices, int selectedIndex) {
    add(parent, label(title, 12, MUTED, true));
    Spinner spinner = new Spinner(this);
    ArrayAdapter<String> adapter =
        new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, choices);
    spinner.setAdapter(adapter);
    spinner.setSelection(Math.max(0, selectedIndex));
    spinner.setContentDescription(title);
    parent.addView(spinner, new LinearLayout.LayoutParams(-1, d(54)));
    gap(parent, 12);
    return spinner;
  }

  private void chips(String[] labels, String selected, java.util.function.Consumer<String> change) {
    HorizontalScrollView scroller = new HorizontalScrollView(this);
    scroller.setHorizontalScrollBarEnabled(false);
    LinearLayout row = new LinearLayout(this);
    for (String name : labels) {
      TextView c = label(name, 13, name.equals(selected) ? WHITE : TEAL, true);
      c.setGravity(Gravity.CENTER);
      c.setPadding(d(16), d(12), d(16), d(12));
      c.setBackground(background(name.equals(selected) ? TEAL : 0xffe4efea, 20));
      LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, d(44));
      lp.rightMargin = d(8);
      row.addView(c, lp);
      c.setOnClickListener(
          v -> {
            if (!busy.isShown()) change.accept(name);
          });
    }
    scroller.addView(row);
    add(content, scroller);
    gap(content, 18);
  }

  private void run(String title, Job job, Done done, boolean quietUnauthorized) {
    int ticket = generation;
    LinearLayout overlay = busy;
    TextView progress = busyLabel;
    overlay.setVisibility(View.VISIBLE);
    progress.setText(title);
    ((InputMethodManager) getSystemService(INPUT_METHOD_SERVICE))
        .hideSoftInputFromWindow(shell.getWindowToken(), 0);
    worker.execute(
        () -> {
          try {
            JSONObject result = job.run();
            runOnUiThread(
                () -> {
                  if (isDestroyed() || ticket != generation) return;
                  overlay.setVisibility(View.GONE);
                  try {
                    done.run(result);
                  } catch (Exception e) {
                    error("The response could not be displayed. Refresh and try again.");
                  }
                });
          } catch (Exception e) {
            runOnUiThread(
                () -> {
                  if (isDestroyed() || ticket != generation) return;
                  overlay.setVisibility(View.GONE);
                  if (e instanceof Api.Failure && ((Api.Failure) e).status == 401) {
                    login();
                    if (!quietUnauthorized) error(e.getMessage());
                  } else
                    error(
                        e instanceof java.net.UnknownHostException
                            ? "No internet connection. Reconnect and try again. Your unsaved form"
                                + " is still here."
                            : e.getMessage() == null
                                ? "Connection failed. Please try again."
                                : e.getMessage());
                });
          }
        });
  }

  private void run(String title, Job job, Done done) {
    run(title, job, done, false);
  }

  private void error(String message) {
    new AlertDialog.Builder(this)
        .setTitle("Could not complete")
        .setMessage(message)
        .setPositiveButton("OK", null)
        .show();
  }

  private void success(String message) {
    Toast.makeText(this, message, Toast.LENGTH_LONG).show();
  }

  private void open(String url) {
    try {
      startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
    } catch (ActivityNotFoundException e) {
      error("No app is available to open this link.");
    }
  }

  private void login() {
    currentCase = "";
    frame("CataTriage AI", "Doctor sign in", false, false);
    FrameLayout hero = new FrameLayout(this);
    hero.setBackground(background(INK, 22));
    IrisView iris = new IrisView(this);
    hero.addView(iris, new FrameLayout.LayoutParams(-1, d(195)));
    content.addView(hero, new LinearLayout.LayoutParams(-1, d(195)));
    gap(content, 24);
    heading("A clearer view.\nA considered decision.");
    para("Your native clinical workspace for patient review, imaging and appointments.");
    EditText username = input(content, "Doctor username", "", false);
    username.setInputType(
        InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
    username.setAutofillHints(View.AUTOFILL_HINT_USERNAME);
    EditText password = input(content, "Password", "", false);
    password.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
    password.setAutofillHints(View.AUTOFILL_HINT_PASSWORD);
    button(
        content,
        "Sign in securely  →",
        () -> {
          String u = text(username), p = password.getText().toString();
          if (u.isEmpty() || p.isEmpty()) {
            error("Enter your doctor username and password.");
            return;
          }
          run(
              "Verifying doctor account…",
              () -> {
                api.bootstrap();
                api.post("/api/mobile/login", Api.form("username", u, "password", p));
                return api.get("/api/mobile/me");
              },
              r -> {
                password.setText("");
                me = r;
                if (r.optBoolean("must_change")) password();
                else refresh("Home");
              });
        },
        true);
    button(
        content,
        "Set up or recover your account",
        () ->
            new AlertDialog.Builder(this)
                .setTitle("Doctor account help")
                .setMessage(
                    "For a new or forgotten password, ask your hospital admin to send a fresh setup"
                        + " email. Open the Firebase email link, set your password and verify your"
                        + " email, then sign in here. You can change an existing password in"
                        + " Profile after signing in.")
                .setPositiveButton("OK", null)
                .show(),
        false);
    gap(content, 18);
    TextView fine =
        label(
            "DOCTOR ACCESS ONLY  ·  Private connection\n"
                + "Research outputs require your independent clinical review.",
            11,
            MUTED,
            false);
    fine.setGravity(Gravity.CENTER);
    add(content, fine);
  }

  private void refresh(String dest) {
    tab = dest;
    frame("Your clinical workspace", dest, false, true);
    run(
        "Refreshing saved records…",
        () -> api.get("/api/mobile/workspace"),
        r -> {
          workspace = r;
          renderTab();
        });
  }

  private void renderTab() {
    switch (tab) {
      case "Patients":
        patients();
        break;
      case "Calendar":
        calendar();
        break;
      case "Inbox":
        inbox();
        break;
      default:
        home();
    }
  }

  private void home() {
    currentCase = "";
    frame("CataTriage doctor", "Today", false, true);
    heading("Hello, " + s(me, "name").replace("Dr. ", "") + ".");
    para("A focused view of your patients and the next decisions to make.");
    LinearLayout hero = card(content);
    hero.setBackground(background(INK, 20));
    LinearLayout row = new LinearLayout(this);
    LinearLayout message = new LinearLayout(this);
    message.setOrientation(LinearLayout.VERTICAL);
    add(message, label("YOUR CARE LIST", 10, 0xff8ee3d4, true));
    add(message, label(String.valueOf(a(workspace, "patients").length()), 48, WHITE, false));
    add(message, label("assigned patients", 13, 0xffd5e7e4, false));
    row.addView(message, new LinearLayout.LayoutParams(0, -2, 1));
    IrisView iris = new IrisView(this);
    row.addView(iris, new LinearLayout.LayoutParams(d(140), d(132)));
    add(hero, row);
    button(hero, "Open patient list", () -> refresh("Patients"), true);
    section("Next on your calendar");
    JSONArray events = a(workspace, "appointments");
    int count = 0;
    for (int i = 0; i < events.length() && count < 3; i++) {
      JSONObject event = at(events, i);
      if (s(event, "scheduled_date").compareTo(s(workspace, "today")) >= 0) {
        eventCard(event);
        count++;
      }
    }
    if (count == 0) para("No upcoming appointments are recorded.");
    button(
        content,
        "Inbox · " + workspace.optInt("unread") + " unread",
        () -> refresh("Inbox"),
        false);
    section("Clinical tools");
    button(content, "Multi-data cataract grade model", () -> grade(), false);
    button(content, "Models & four processing agents", () -> models(), false);
    section("Reminders");
    JSONArray notices = a(workspace, "notifications");
    if (notices.length() == 0) para("No reminders for your account.");
    for (int i = 0; i < notices.length(); i++) {
      JSONObject n = at(notices, i);
      info(s(n, "title"), s(n, "body") + "\n" + s(n, "due_date"));
    }
  }

  private void patients() {
    currentCase = "";
    frame("Assigned to you", "Patients", false, true);
    heading("Your care list");
    para("Search by name or patient ID. Open a record to review images and clinical findings.");
    EditText search = input(content, "Search patients", "", false);
    LinearLayout list = new LinearLayout(this);
    list.setOrientation(LinearLayout.VERTICAL);
    add(content, list);
    fillPatients(list, "");
    search.addTextChangedListener(
        new TextWatcher() {
          public void beforeTextChanged(CharSequence t, int a, int c, int f) {}

          public void onTextChanged(CharSequence t, int st, int before, int count) {
            fillPatients(list, t.toString());
          }

          public void afterTextChanged(Editable e) {}
        });
  }

  private void fillPatients(LinearLayout list, String query) {
    list.removeAllViews();
    JSONArray ps = a(workspace, "patients");
    int found = 0;
    for (int i = 0; i < ps.length(); i++) {
      JSONObject p = at(ps, i);
      if (!(s(p, "full_name") + s(p, "case_id"))
          .toLowerCase(Locale.ROOT)
          .contains(query.toLowerCase(Locale.ROOT))) continue;
      found++;
      LinearLayout c = card(list);
      add(c, label(s(p, "case_id") + "  ·  " + s(p, "age") + " years", 11, TEAL, true));
      gap(c, 5);
      add(c, label(s(p, "full_name"), 21, INK, true));
      gap(c, 7);
      add(
          c,
          label(
              (s(p, "approved_tier").isEmpty() ? "Awaiting doctor review" : s(p, "approved_tier"))
                  + "  ·  "
                  + nice(s(p, "modality")),
              13,
              MUTED,
              false));
      button(c, "Open record  →", () -> loadCase(s(p, "case_id"), "Overview"), false);
    }
    if (found == 0) add(list, label("No matching assigned patients.", 15, MUTED, false));
  }

  private void loadCase(String id, String view) {
    currentCase = id;
    caseTab = view;
    run(
        "Opening patient record…",
        () -> api.get("/api/mobile/patients/" + id),
        r -> {
          patientData = r;
          caseView();
        });
  }

  private void caseView() {
    JSONObject p = o(patientData, "patient"), c = o(patientData, "case");
    frame(currentCase, s(p, "full_name"), true, true);
    chips(
        new String[] {"Overview", "Images", "Review", "History"},
        caseTab,
        choice -> {
          caseTab = choice;
          caseView();
        });
    switch (caseTab) {
      case "Images":
        images();
        break;
      case "Review":
        review();
        break;
      case "History":
        history();
        break;
      default:
        heading("Patient overview");
        info(
            "Clinical status",
            nice(s(c, "status"))
                + " · "
                + (s(c, "approved_tier").isEmpty()
                    ? "Priority not assigned"
                    : s(c, "approved_tier")));
        info("Contact", s(p, "phone") + "\n" + s(p, "email") + "\n" + s(p, "address"));
        button(content, "Call patient", () -> open("tel:" + s(p, "phone")), false);
        info("Medical history", s(p, "medical_history"));
        info("Reported symptoms", s(c, "symptoms"));
        info("Clinical notes", s(c, "notes"));
        button(content, "Edit symptoms & clinical notes", () -> editNotes(), true);
        button(content, "Capture / upload eye images", () -> upload(), false);
        button(content, "Create full report PDF", () -> report(), false);
        button(content, "Message this patient", () -> compose("patient:" + currentCase), false);
        section("Patient self-assessments");
        JSONArray assessments = a(patientData, "assessments");
        if (assessments.length() == 0) para("No self-assessments recorded.");
        for (int i = 0; i < assessments.length(); i++) {
          JSONObject item = at(assessments, i);
          info(s(item, "submitted_at"), s(item, "findings") + "\n" + s(item, "review_status"));
        }
    }
  }

  private void images() {
    heading("Image analysis");
    JSONObject summary = o(patientData, "eye_summary");
    para(s(summary, "headline"));
    para(s(summary, "scope"));
    JSONArray entries = a(summary, "entries");
    for (int i = 0; i < entries.length(); i++) {
      JSONObject entry = at(entries, i);
      info(s(entry, "label"), s(entry, "status") + "\n" + s(entry, "detail"));
    }
    JSONArray images = a(patientData, "images");
    if (images.length() == 0)
      info(
          "No images in this round",
          "Only images you actually upload are shown. Earlier rounds remain in History.");
    for (int i = 0; i < images.length(); i++) imageCard(at(images, i));
    button(content, "Start a new image upload round", () -> upload(), true);
    para(
        "Eye side follows the upload label. The research model cannot establish anatomical"
            + " laterality or a clinical diagnosis.");
  }

  private void imageCard(JSONObject image) {
    LinearLayout c = card(content);
    String side = s(image, "eye_side");
    add(c, label(side.equals("Not recorded") ? "Eye side unknown" : side + " eye", 17, INK, true));
    gap(c, 12);
    ImageView photo = new ImageView(this);
    photo.setScaleType(ImageView.ScaleType.FIT_CENTER);
    photo.setContentDescription("Uploaded " + side + " eye image");
    photo.setBackground(background(0xffeaf0ed, 12));
    c.addView(photo, new LinearLayout.LayoutParams(-1, d(210)));
    int ticket = generation;
    worker.execute(
        () -> {
          try {
            byte[] bytes =
                api.request("GET", "/api/mobile/images/" + image.optInt("id"), null, null);
            Bitmap bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.length);
            runOnUiThread(
                () -> {
                  if (ticket == generation) photo.setImageBitmap(bitmap);
                });
          } catch (Exception ignored) {
            runOnUiThread(
                () -> {
                  if (ticket == generation)
                    photo.setContentDescription("Image could not load. Refresh to try again.");
                });
          }
        });
    gap(c, 12);
    renderAnalysis(c, o(image, "analysis"));
    add(c, label(s(image, "created_at"), 11, MUTED, false));
  }

  private void renderAnalysis(LinearLayout parent, JSONObject result) {
    if (!"ok".equals(s(result, "status"))) {
      add(parent, label("Analysis " + nice(s(result, "status")), 16, INK, true));
      add(parent, label(s(result, "reason"), 13, MUTED, false));
    } else {
      add(
          parent,
          label(
              s(result, "top_class")
                  + " · "
                  + String.format(Locale.ROOT, "%.1f%%", result.optDouble("confidence") * 100),
              20,
              TEAL,
              true));
      JSONObject probs = o(result, "probabilities");
      Iterator<String> keys = probs.keys();
      while (keys.hasNext()) {
        String key = keys.next();
        add(
            parent,
            label(
                key + "  " + String.format(Locale.ROOT, "%.1f%%", probs.optDouble(key) * 100),
                12,
                MUTED,
                false));
        ProgressBar bar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        bar.setMax(1000);
        bar.setProgress((int) (probs.optDouble(key) * 1000));
        parent.addView(bar, new LinearLayout.LayoutParams(-1, d(7)));
        gap(parent, 7);
      }
      add(
          parent,
          label(
              "Model confidence is not a measured probability of disease. Doctor review required.",
              12,
              MUTED,
              false));
    }
    JSONArray agents = a(result, "agent_workflow");
    for (int j = 0; j < agents.length(); j++) {
      JSONObject agent = at(agents, j);
      gap(parent, 12);
      add(parent, label(s(agent, "agent"), 12, TEAL, true));
      add(parent, label(s(agent, "status") + " · " + s(agent, "summary"), 12, MUTED, false));
    }
  }

  private void editNotes() {
    frame(currentCase, "Clinical context", true, true);
    para(
        "Save the doctor's reported symptoms and examination notes. These are used by planning and"
            + " clinical advice.");
    JSONObject c = o(patientData, "case");
    EditText symptoms = input(content, "Reported symptoms", s(c, "symptoms"), true),
        notes = input(content, "Clinical notes", s(c, "notes"), true);
    button(
        content,
        "Save clinical context",
        () ->
            run(
                "Saving notes…",
                () ->
                    api.post(
                        "/api/mobile/patients/" + currentCase + "/notes",
                        Api.form("symptoms", text(symptoms), "notes", text(notes))),
                r -> {
                  success("Notes saved");
                  loadCase(currentCase, "Overview");
                }),
        true);
  }

  private void review() {
    JSONObject c = o(patientData, "case"),
        assess = o(patientData, "month_assessment"),
        plan = o(patientData, "month_plan");
    heading("Your clinical decision");
    info(
        "Priority tiers",
        "Tier 1 · Higher priority: review and plan first.\n"
            + "Tier 2 · Intermediate priority.\n"
            + "Tier 3 · Routine priority.\n"
            + "These labels do not define a cataract grade or a safe waiting period.");
    Spinner decision =
        select(
            content,
            "Review decision",
            new String[] {
              "Approve manual tier",
              "Modify manual tier",
              "Escalate for review",
              "Return for information"
            },
            0);
    String tier = s(c, "approved_tier");
    Spinner tiers =
        select(
            content,
            "Doctor-selected tier",
            new String[] {"Choose tier", "Tier 1", "Tier 2", "Tier 3"},
            tier.equals("Tier 1") ? 1 : tier.equals("Tier 2") ? 2 : tier.equals("Tier 3") ? 3 : 0);
    EditText reason = input(content, "Reason for review", s(c, "approval_reason"), true);
    button(
        content,
        "Record independent review",
        () -> {
          String[] decisions = {"approve", "modify", "escalate", "reject"};
          String selectedTier =
              tiers.getSelectedItemPosition() == 0 ? "" : tiers.getSelectedItem().toString();
          run(
              "Saving review…",
              () ->
                  api.post(
                      "/api/mobile/patients/" + currentCase + "/review",
                      Api.form(
                          "decision",
                          decisions[decision.getSelectedItemPosition()],
                          "tier",
                          selectedTier,
                          "reason",
                          text(reason))),
              r -> loadCase(currentCase, "Review"));
        },
        true);
    if (!s(plan, "approved_month").isEmpty())
      info(
          plan.optBoolean("is_current")
              ? "Doctor-approved surgery month"
              : "Month approval needs fresh review",
          s(plan, "approved_month") + "\n" + s(plan, "approval_reason"));
    section("AI month planning");
    para(
        "The doctor approves a month. The hospital admin selects the exact free date and time."
            + " Model confidence is not used to justify delaying care.");
    EditText symptoms = input(content, "Reported symptoms", s(c, "symptoms"), true),
        notes = input(content, "Clinical notes", s(c, "notes"), true);
    String[] impactCodes = {"unknown", "mild", "moderate", "severe"},
        progressCodes = {"unknown", "stable", "progressive"},
        preferenceCodes = {"soon", "balanced", "later"};
    Spinner impact =
        select(
            content,
            "Doctor-assessed functional impact",
            new String[] {"Not assessed", "Mild", "Moderate", "Severe"},
            Math.max(0, Arrays.asList(impactCodes).indexOf(s(assess, "functional_impact"))));
    Spinner progression =
        select(
            content,
            "Doctor-assessed progression",
            new String[] {"Not assessed", "Stable", "Progressive"},
            Math.max(0, Arrays.asList(progressCodes).indexOf(s(assess, "progression"))));
    Spinner preference =
        select(
            content,
            "Planning preference after clinical discussion",
            new String[] {
              "Earlier consideration",
              "Balanced elective planning",
              "Later if clinically appropriate"
            },
            Math.max(0, Arrays.asList(preferenceCodes).indexOf(s(assess, "planning_preference"))));
    para(
        "Mild, stable routine cases can be considered for later planning when the doctor records"
            + " that preference. A proposed month is not a medically validated safe waiting time.");
    button(
        content,
        "Suggest a surgery month",
        () -> {
          Map<String, String> values =
              Api.form(
                  "symptoms",
                  text(symptoms),
                  "notes",
                  text(notes),
                  "functional_impact",
                  impactCodes[impact.getSelectedItemPosition()],
                  "progression",
                  progressCodes[progression.getSelectedItemPosition()],
                  "planning_preference",
                  preferenceCodes[preference.getSelectedItemPosition()]);
          run(
              "Reviewing clinical context and month availability…",
              () -> api.post("/api/mobile/patients/" + currentCase + "/suggestion", values),
              r -> suggestion(o(r, "suggestion")));
        },
        true);
    button(
        content,
        "Choose a month for admin scheduling",
        () -> approveMonth(new JSONObject()),
        false);
  }

  private void bullets(LinearLayout parent,JSONArray lines) {
    for(int index=0;index<lines.length();index++) {
      add(parent,label("•  "+lines.optString(index),14,INK,false));
      gap(parent,9);
    }
  }

  private void suggestion(JSONObject result) {
    frame(currentCase, "Surgery month proposal", true, true);
    heading(s(result, "suggested_month_label"));
    para(s(result, "provider_label"));
    LinearLayout reasons = card(content);
    add(reasons, label("Why this month was considered", 18, TEAL, true));
    gap(reasons, 12);
    bullets(reasons, a(result, "reason_points"));
    para(s(result, "integration_status"));
    JSONObject clinical = o(result, "clinical_review");
    info("Clinical review", s(clinical, "status"));
    LinearLayout advice = card(content);
    bullets(advice, a(clinical, "advice"));
    section("Information to confirm");
    LinearLayout missing = card(content);
    bullets(missing, a(clinical, "missing_information"));
    para(s(clinical, "limitations"));
    if (!s(result, "suggested_month").isEmpty())
      button(content, "Review & approve a month", () -> approveMonth(result), true);
    button(content, "Return to clinical review", () -> loadCase(currentCase, "Review"), false);
  }

  private void approveMonth(JSONObject result) {
    frame(currentCase, "Approve surgery month", true, true);
    heading("Your month decision");
    para(
        "Confirm an elective planning month after clinical assessment. The hospital admin will"
            + " select a free date inside it. Changed symptoms or evidence require fresh review.");
    Calendar cursor = Calendar.getInstance();
    List<String> codes = new ArrayList<>(), labels = new ArrayList<>();
    String preferred = s(result, "suggested_month");
    if (preferred.isEmpty()) preferred = s(o(patientData, "month_plan"), "approved_month");
    for (int i = 0; i < 13; i++) {
      codes.add(new SimpleDateFormat("yyyy-MM", Locale.ROOT).format(cursor.getTime()));
      labels.add(new SimpleDateFormat("MMMM yyyy", Locale.getDefault()).format(cursor.getTime()));
      cursor.add(Calendar.MONTH, 1);
    }
    Spinner month =
        select(
            content,
            "Doctor-approved month",
            labels.toArray(new String[0]),
            Math.max(0, codes.indexOf(preferred)));
    EditText reason =
        input(
            content,
            "Clinical reason for this month",
            s(o(patientData, "month_plan"), "approval_reason"),
            true);
    CheckBox confirm = new CheckBox(this);
    confirm.setText(R.string.month_attestation);
    confirm.setTextColor(INK);
    add(content, confirm);
    JSONObject assessment =
        result.has("assessment") ? o(result, "assessment") : o(patientData, "month_assessment");
    String evidence =
        result.has("evidence_hash") ? s(result, "evidence_hash") : s(patientData, "evidence_hash");
    button(
        content,
        "Approve month for hospital admin",
        () -> {
          if (!confirm.isChecked()) {
            error("Confirm your independent clinical assessment first.");
            return;
          }
          Map<String, String> values =
              Api.form(
                  "approved_month",
                  codes.get(month.getSelectedItemPosition()),
                  "reason",
                  text(reason),
                  "attestation",
                  "yes",
                  "evidence_hash",
                  evidence,
                  "functional_impact",
                  s(assessment, "functional_impact"),
                  "progression",
                  s(assessment, "progression"),
                  "planning_preference",
                  s(assessment, "planning_preference"));
          run(
              "Saving your approved month…",
              () -> api.post("/api/mobile/patients/" + currentCase + "/month", values),
              r -> {
                success("Month approved. The hospital admin can choose a free date.");
                loadCase(currentCase, "Review");
              });
        },
        true);
  }

  private EditText dateInput(String title, String value) {
    EditText e = input(content, title, value, false);
    e.setFocusable(false);
    e.setOnClickListener(
        v -> {
          Calendar cal = Calendar.getInstance();
          try {
            cal.setTime(new SimpleDateFormat("yyyy-MM-dd", Locale.ROOT).parse(text(e)));
          } catch (Exception ignored) {
          }
          new DatePickerDialog(
                  this,
                  (picker, y, m, day) ->
                      e.setText(String.format(Locale.ROOT, "%04d-%02d-%02d", y, m + 1, day)),
                  cal.get(Calendar.YEAR),
                  cal.get(Calendar.MONTH),
                  cal.get(Calendar.DAY_OF_MONTH))
              .show();
        });
    return e;
  }

  private void history() {
    heading("Record history");
    JSONArray old = a(patientData, "older_images");
    section("Earlier image rounds · " + old.length() + " images");
    for (int i = 0; i < old.length(); i++) imageCard(at(old, i));
    section("Clinical audit");
    JSONArray history = a(patientData, "history");
    for (int i = 0; i < history.length(); i++) {
      JSONObject h = at(history, i);
      info(nice(s(h, "action")) + " · " + s(h, "timestamp"), s(h, "details"));
    }
    section("Patient communication");
    JSONArray messages = a(patientData, "messages");
    for (int i = 0; i < messages.length(); i++) {
      JSONObject message = at(messages, i);
      info(s(message, "sender") + " · " + s(message, "sent_at"), s(message, "body"));
    }
  }

  private void upload() {
    selected.clear();
    frame(currentCase, "Capture both eyes", true, true);
    heading("Start a fresh round");
    para(
        "Choose the correct eye label, or use Eye side unknown. No image is selected by default."
            + " Only selected originals will be uploaded.");
    imageOptions = new LinearLayout(this);
    imageOptions.setOrientation(LinearLayout.VERTICAL);
    add(content, imageOptions);
    renderSelections();
    JSONObject c = o(patientData, "case");
    Spinner modality =
        select(
            content,
            "Image type",
            new String[] {"Slit-lamp", "Fundus"},
            s(c, "modality").equals("fundus") ? 1 : 0);
    Spinner illumination =
        select(
            content,
            "Slit-lamp illumination",
            new String[] {
              "Diffuse Illumination", "Direct Focal Illumination", "Retro Illumination"
            },
            0);
    EditText symptoms = input(content, "Reported symptoms", s(c, "symptoms"), true),
        notes = input(content, "Clinical notes", s(c, "notes"), true);
    button(
        content,
        "Upload originals & run four agents",
        () -> {
          if (selected.isEmpty()) {
            error("Choose at least one eye image. Nothing has been uploaded.");
            return;
          }
          LinkedHashMap<String, Uri> round = new LinkedHashMap<>(selected);
          run(
              "Validating selected images…",
              () -> {
                List<String> ids = new ArrayList<>();
                for (Map.Entry<String, Uri> entry : round.entrySet()) {
                  byte[] bytes =
                      Api.read(
                          getContentResolver().openInputStream(entry.getValue()), 8 * 1024 * 1024);
                  BitmapFactory.Options bounds = new BitmapFactory.Options();
                  bounds.inJustDecodeBounds = true;
                  BitmapFactory.decodeByteArray(bytes, 0, bytes.length, bounds);
                  if (bounds.outWidth < 128 || bounds.outHeight < 128)
                    throw new IOException("Choose an eye photograph of at least 128 × 128 pixels.");
                  String field =
                      entry.getKey().equals("Left")
                          ? "left_images"
                          : entry.getKey().equals("Right") ? "right_images" : "unknown_images";
                  api.upload(
                      currentCase,
                      field,
                      entry.getKey() + "-eye",
                      bytes,
                      msg -> runOnUiThread(() -> busyLabel.setText(msg)),
                      ids);
                }
                runOnUiThread(() -> busyLabel.setText(R.string.running_agents));
                return api.post(
                    "/api/mobile/intake",
                    Api.form(
                        "case_id",
                        currentCase,
                        "modality",
                        modality.getSelectedItemPosition() == 0 ? "slit_lamp" : "fundus",
                        "illumination_type",
                        illumination.getSelectedItem().toString(),
                        "symptoms",
                        text(symptoms),
                        "notes",
                        text(notes),
                        "cloud_uploads",
                        new JSONArray(ids).toString()));
              },
              r -> {
                selected.clear();
                success("Original images saved and analysed");
                loadCase(currentCase, "Images");
              });
        },
        true);
    para(
        "JPEG, PNG or WebP · up to 8 MB each. Images from this round are grouped together; earlier"
            + " uploads remain in history.");
  }

  private void renderSelections() {
    imageOptions.removeAllViews();
    for (String side : new String[] {"Left", "Right", "Unknown"}) {
      LinearLayout c = card(imageOptions);
      String name = side.equals("Unknown") ? "Eye side unknown" : side + " eye";
      add(c, label(name, 18, INK, true));
      Uri uri = selected.get(side);
      add(
          c,
          label(
              uri == null ? "No image selected" : "Image selected for this round",
              12,
              uri == null ? MUTED : TEAL,
              false));
      if (uri != null) {
        ImageView preview = new ImageView(this);
        preview.setScaleType(ImageView.ScaleType.FIT_CENTER);
        c.addView(preview, new LinearLayout.LayoutParams(-1, d(130)));
        try (InputStream in = getContentResolver().openInputStream(uri)) {
          BitmapFactory.Options options = new BitmapFactory.Options();
          options.inSampleSize = 4;
          preview.setImageBitmap(BitmapFactory.decodeStream(in, null, options));
        } catch (Exception ignored) {
        }
        button(
            c,
            "Remove image",
            () -> {
              selected.remove(side);
              renderSelections();
            },
            false);
      }
      button(
          c,
          uri == null ? "Select / capture image" : "Replace image",
          () -> {
            pendingSide = side;
            new AlertDialog.Builder(this)
                .setTitle(name)
                .setItems(
                    new String[] {"Choose original from files", "Take a photograph"},
                    (dialog, index) -> {
                      if (index == 0) {
                        Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                        intent.setType("image/*");
                        intent.addCategory(Intent.CATEGORY_OPENABLE);
                        startActivityForResult(intent, 41);
                      } else capture();
                    })
                .show();
          },
          false);
    }
  }

  private void capture() {
    try {
      String file = "capture-" + UUID.randomUUID() + ".jpg";
      cameraUri = Uri.parse("content://" + BuildConfig.APPLICATION_ID + ".capture/" + file);
      Intent intent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
      intent.putExtra(MediaStore.EXTRA_OUTPUT, cameraUri);
      intent.addFlags(
          Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
      intent.setClipData(ClipData.newRawUri("Eye photograph", cameraUri));
      startActivityForResult(intent, 42);
    } catch (ActivityNotFoundException e) {
      error("No camera app was found. Choose an existing photograph instead.");
    }
  }

  @Override
  protected void onActivityResult(int request, int result, Intent data) {
    super.onActivityResult(request, result, data);
    if (result != RESULT_OK) return;
    if (request == 44 && data != null && data.getData() != null) {
      profilePhoto = data.getData();
      profilePhotoStatus.setText(R.string.profile_photo_selected);
      try (InputStream in = getContentResolver().openInputStream(profilePhoto)) {
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inSampleSize = 4;
        profilePreview.setImageBitmap(BitmapFactory.decodeStream(in, null, options));
      } catch (Exception e) {
        error("The selected photograph could not be read.");
      }
    } else if (request == 41 && data != null && data.getData() != null) {
      selected.put(pendingSide, data.getData());
      renderSelections();
    } else if (request == 42 && cameraUri != null) {
      selected.put(pendingSide, cameraUri);
      renderSelections();
    } else if (request == 43 && data != null && data.getData() != null && pdfBytes != null) {
      try (OutputStream stream = getContentResolver().openOutputStream(data.getData())) {
        stream.write(pdfBytes);
        success("Report PDF saved");
      } catch (Exception e) {
        error("The PDF could not be saved. Choose another location.");
      }
    }
  }

  private void calendar() {
    currentCase = "";
    frame("Consultations & surgery", "Calendar", false, true);
    heading("A considered schedule");
    para(
        "Your recorded consultations and confirmed surgeries. Tap a record to review the patient or"
            + " add a personal reminder.");
    JSONArray events = a(workspace, "appointments");
    if (events.length() == 0)
      info(
          "No appointments",
          "Your hospital has not scheduled any appointments for these patients.");
    for (int i = 0; i < events.length(); i++) eventCard(at(events, i));
    button(content, "Refresh calendar", () -> refresh("Calendar"), false);
  }

  private void eventCard(JSONObject event) {
    LinearLayout c = card(content);
    add(c, label(s(event, "scheduled_date") + "  /  " + s(event, "slot"), 12, TEAL, true));
    gap(c, 6);
    add(c, label(s(event, "patient_alias"), 20, INK, true));
    add(c, label(s(event, "kind") + " · " + s(event, "case_id"), 13, MUTED, false));
    button(c, "View patient", () -> loadCase(s(event, "case_id"), "Review"), false);
    button(
        c,
        "Add to device calendar",
        () -> {
          try {
            Date start =
                new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.ROOT)
                    .parse(s(event, "scheduled_date") + " " + s(event, "slot"));
            Intent intent = new Intent(Intent.ACTION_INSERT, CalendarContract.Events.CONTENT_URI);
            intent.putExtra(
                CalendarContract.Events.TITLE,
                "CataTriage " + s(event, "kind") + " · " + s(event, "case_id"));
            intent.putExtra(CalendarContract.EXTRA_EVENT_BEGIN_TIME, start.getTime());
            intent.putExtra(CalendarContract.EXTRA_EVENT_END_TIME, start.getTime() + 3600000);
            startActivity(intent);
          } catch (Exception ex) {
            error("No calendar app is available. Your appointment is saved in CataTriage.");
          }
        },
        false);
  }

  private void inbox() {
    currentCase = "";
    frame("Doctor communications", "Inbox", false, true);
    chips(
        new String[] {"Inbox", "Sent"},
        mailbox.equals("inbox") ? "Inbox" : "Sent",
        choice -> {
          mailbox = choice.equals("Inbox") ? "inbox" : "sent";
          inbox();
        });
    button(content, "Compose message  +", () -> compose(""), true);
    LinearLayout list = new LinearLayout(this);
    list.setOrientation(LinearLayout.VERTICAL);
    add(content, list);
    run(
        "Loading " + mailbox + "…",
        () -> api.get("/api/mobile/mailbox?box=" + mailbox),
        r -> {
          JSONArray messages = a(r, "messages");
          if (messages.length() == 0)
            add(list, label("No messages in this folder.", 15, MUTED, false));
          for (int i = 0; i < messages.length(); i++) {
            JSONObject message = at(messages, i);
            LinearLayout c = card(list);
            add(c, label(s(message, "subject"), 18, INK, true));
            add(
                c,
                label(
                    (mailbox.equals("inbox")
                            ? "From " + s(message, "sender")
                            : "To " + s(message, "recipient"))
                        + " · "
                        + s(message, "created_at"),
                    11,
                    TEAL,
                    false));
            gap(c, 8);
            add(c, label(s(message, "body"), 14, INK, false));
            if("surgery".equals(s(message,"category"))) {
              add(c,label(nice(s(message,"delivery_status"))+" · "+s(message,"delivery_detail"),12,MUTED,false));
              String phone=s(message,"recipient_phone").replaceAll("[^0-9]","");
              if(!phone.isEmpty() && !"accepted".equals(s(message,"delivery_status")) && !"sending".equals(s(message,"delivery_status"))) {
                button(c,"Open WhatsApp message",()->open("https://wa.me/"+phone+"?text="+Uri.encode(s(message,"body"))),false);
              }
            }
            if (mailbox.equals("inbox") && !message.isNull("id") && s(message, "read_at").isEmpty())
              button(
                  c,
                  "Mark read",
                  () ->
                      run(
                          "Updating inbox…",
                          () ->
                              api.post(
                                  "/api/mobile/messages/" + message.optInt("id") + "/read",
                                  Api.form()),
                          v -> inbox()),
                  false);
          }
        });
  }

  private void compose(String recipient) {
    frame("Internal communications", "New message", true, true);
    List<String> labels = new ArrayList<>(), values = new ArrayList<>();
    JSONArray staff = a(workspace, "staff");
    for (int i = 0; i < staff.length(); i++) {
      JSONObject person = at(staff, i);
      if (s(person, "username").equals(s(me, "username"))) continue;
      labels.add(s(person, "display_name") + " · " + s(person, "role"));
      values.add("staff:" + s(person, "username"));
    }
    JSONArray patients = a(workspace, "patients");
    for (int i = 0; i < patients.length(); i++) {
      JSONObject person = at(patients, i);
      labels.add(s(person, "full_name") + " · Patient");
      values.add("patient:" + s(person, "case_id"));
    }
    if (values.isEmpty()) {
      para("There are no available recipients.");
      return;
    }
    Spinner target =
        select(
            content,
            "Recipient",
            labels.toArray(new String[0]),
            Math.max(0, values.indexOf(recipient)));
    EditText subject = input(content, "Subject", "", false),
        body = input(content, "Message", "", true);
    para(
        "Messages to staff appear in their inbox. Patient messages are stored in the assigned"
            + " patient's communication history; this does not send an email or WhatsApp message.");
    button(
        content,
        "Send internal message",
        () ->
            new AlertDialog.Builder(this)
                .setTitle("Send this message?")
                .setMessage(labels.get(target.getSelectedItemPosition()))
                .setNegativeButton("Cancel", null)
                .setPositiveButton(
                    "Send",
                    (dlg, w) ->
                        run(
                            "Saving message…",
                            () ->
                                api.post(
                                    "/api/mobile/messages",
                                    Api.form(
                                        "recipient",
                                        values.get(target.getSelectedItemPosition()),
                                        "subject",
                                        text(subject),
                                        "body",
                                        text(body),
                                        "category",
                                        values
                                                .get(target.getSelectedItemPosition())
                                                .startsWith("patient:")
                                            ? "patient"
                                            : "other")),
                            r -> {
                              success("Message saved");
                              currentCase = "";
                              tab = "Inbox";
                              mailbox = "sent";
                              inbox();
                            }))
                .show(),
        true);
  }

  private Uri profilePhoto;
  private ImageView profilePreview;
  private TextView profilePhotoStatus;

  private void profile() {
    profilePhoto = null;
    frame("Account & preferences", "Your profile", true, true);
    heading(s(me, "name"));
    JSONObject p = o(me, "profile");
    profilePreview = new ImageView(this);
    profilePreview.setScaleType(ImageView.ScaleType.FIT_CENTER);
    profilePreview.setContentDescription("Your profile photograph");
    content.addView(profilePreview, new LinearLayout.LayoutParams(-1, d(150)));
    if (!s(p, "profile_image").isEmpty()) {
      int ticket = generation;
      worker.execute(
          () -> {
            try {
              byte[] bytes = api.request("GET", "/api/mobile/profile/image", null, null);
              Bitmap photo = BitmapFactory.decodeByteArray(bytes, 0, bytes.length);
              runOnUiThread(
                  () -> {
                    if (ticket == generation) profilePreview.setImageBitmap(photo);
                  });
            } catch (Exception ignored) {
            }
          });
    }
    profilePhotoStatus = label("Choose a photograph, or keep your current one.", 12, MUTED, false);
    add(content, profilePhotoStatus);
    button(
        content,
        "Change profile photograph",
        () -> {
          Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT);
          intent.setType("image/*");
          intent.addCategory(Intent.CATEGORY_OPENABLE);
          startActivityForResult(intent, 44);
        },
        false);
    EditText username =
        input(
            content,
            "Sign-in username",
            s(me, "login_name").isEmpty() ? s(me, "username") : s(me, "login_name"),
            false);
    username.setInputType(
        InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
    EditText current = input(content, "Current password (required to change username)", "", false);
    current.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
    para(
        "Changing the username signs out existing sessions. Your patients and clinical history"
            + " remain attached to your account.");
    button(
        content,
        "Save profile",
        () -> {
          String newName = text(username),
              pw = current.getText().toString(),
              owner = s(me, "username");
          Uri photo = profilePhoto;
          run(
              "Saving your profile…",
              () -> {
                List<String> ids = new ArrayList<>();
                if (photo != null) {
                  byte[] bytes =
                      Api.read(getContentResolver().openInputStream(photo), 8 * 1024 * 1024);
                  api.uploadFor(
                      "/api/mobile/profile",
                      owner,
                      "profile_image",
                      "profile-photo",
                      bytes,
                      msg -> runOnUiThread(() -> busyLabel.setText(msg)),
                      ids);
                }
                JSONObject saved =
                    api.post(
                        "/api/mobile/profile",
                        Api.form(
                            "username",
                            owner,
                            "new_login_name",
                            newName,
                            "current_password",
                            pw,
                            "cloud_uploads",
                            new JSONArray(ids).toString()));
                if (!saved.optBoolean("renamed")) saved.put("me", api.get("/api/mobile/me"));
                return saved;
              },
              r -> {
                if (r.optBoolean("renamed")) {
                  api.clear();
                  me = new JSONObject();
                  login();
                  success("Username changed. Sign in with " + s(r, "login_name"));
                } else {
                  me = o(r, "me");
                  profile();
                  success("Profile saved");
                }
              });
        },
        true);
    button(content, "Change password securely", () -> password(), true);
    info(
        "Working details",
        s(p, "working_days") + "\n" + s(p, "work_start") + "–" + s(p, "work_end"));
    button(content, "Request leave", () -> leave(), false);
    button(content, "Doctor directory", () -> directory(), false);
    button(content, "Models & agents", () -> models(), false);
    button(
        content,
        "Sign out",
        () ->
            run(
                "Signing out…",
                () -> api.post("/api/mobile/logout", Api.form()),
                r -> {
                  api.clear();
                  workspace = new JSONObject();
                  patientData = new JSONObject();
                  me = new JSONObject();
                  login();
                }),
        false);
    para("CataTriage Doctor 1.1.0 · Online connection required");
  }

  private void password() {
    frame("Account security", "Change password", false, false);
    para(
        "Use your current password and a different new password of at least 12 characters. Your"
            + " existing sessions will be revoked.");
    EditText current = input(content, "Current password", "", false),
        next = input(content, "New password", "", false),
        again = input(content, "Confirm new password", "", false);
    for (EditText field : new EditText[] {current, next, again}) {
      field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
      field.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
    }
    button(
        content,
        "Update password securely",
        () ->
            run(
                "Updating password…",
                () ->
                    api.post(
                        "/api/mobile/password",
                        Api.form(
                            "username",
                            s(me, "username"),
                            "current_password",
                            current.getText().toString(),
                            "new_password",
                            next.getText().toString(),
                            "confirmation",
                            again.getText().toString())),
                r -> {
                  api.clear();
                  login();
                  success("Password changed. Sign in again.");
                }),
        true);
    if (!me.optBoolean("must_change")) button(content, "Back to profile", () -> profile(), false);
  }

  private void leave() {
    frame("Time away", "Request leave", true, true);
    EditText date = dateInput("Leave date", "");
    Spinner type =
        select(content, "Leave type", new String[] {"Full day", "Morning", "Evening"}, 0);
    button(
        content,
        "Review leave request",
        () ->
            submitLeave(
                text(date),
                new String[] {"full_day", "morning", "evening"}[type.getSelectedItemPosition()],
                ""),
        true);
    section("Your leave requests");
    JSONArray leaves = a(workspace, "leaves");
    for (int i = 0; i < leaves.length(); i++) {
      JSONObject item = at(leaves, i);
      info(s(item, "leave_date"), nice(s(item, "leave_type")) + " · " + s(item, "status"));
    }
  }

  private void submitLeave(String date, String type, String confirmed) {
    run(
        "Checking affected bookings…",
        () ->
            api.post(
                "/api/mobile/leave",
                Api.form("leave_date", date, "leave_type", type, "confirmed", confirmed)),
        r -> {
          if (r.optBoolean("needs_confirmation"))
            new AlertDialog.Builder(this)
                .setTitle("Affected appointments")
                .setMessage(
                    a(r, "affected").length()
                        + " bookings fall within this leave. The hospital admin will be notified to"
                        + " review them.")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Submit request", (dialog, w) -> submitLeave(date, type, "yes"))
                .show();
          else {
            success("Leave request submitted");
            refresh("Home");
          }
        });
  }

  private void directory() {
    frame("Hospital contacts", "Doctor directory", true, true);
    JSONArray directory = a(workspace, "directory");
    for (int i = 0; i < directory.length(); i++) {
      JSONObject person = at(directory, i);
      info(
          s(person, "display_name"),
          s(person, "specialty")
              + "\n"
              + s(person, "hospital")
              + "\n"
              + s(person, "phone")
              + "\n"
              + s(person, "email")
              + "\n"
              + s(person, "working_hours"));
      button(content, "Message doctor", () -> compose("staff:" + s(person, "username")), false);
    }
  }

  private void models() {
    frame("Research evidence", "Models & agents", true, true);
    heading("Evidence before action");
    info(
        "Two real-data research models",
        "Multi-data cataract grade model · 53.69% held-out accuracy (298 test patients).\n"
            + "Clinical fusion slit-lamp model · 52.5% held-out accuracy (40 test images).\n\n"
            + "These are research measurements, not clinical validation. The fusion model's"
            + " normal-class recall was 12.5%, so negative predictions must not be used to rule out"
            + " disease.");
    info(
        "1 · Data preprocessing",
        "Checks uploaded bytes, image dimensions and required fields. Each image retains its"
            + " doctor-selected eye label.");
    info(
        "2 · Model inference",
        "Runs the compatible locked model. Imaging analysis uses the real-data CNN fusion"
            + " checkpoint; the separate multi-data grade tool uses structured measurements.");
    info(
        "3 · Safety & rule validation",
        "Flags unavailable, uncertain and incompatible predictions. No model assigns clinical"
            + " priority or authorises surgery.");
    info(
        "4 · Explanation & reporting",
        "Presents image findings, probabilities, limitations and the full audit trace for the"
            + " doctor's review.");
    button(content, "Open multi-data grade tool", () -> grade(), true);
    button(
        content,
        "Refresh model evidence",
        () ->
            run(
                "Loading measured model evidence…",
                () -> api.get("/api/mobile/models"),
                r -> {
                  JSONArray models = a(r, "models");
                  for (int i = 0; i < models.length(); i++) {
                    JSONObject model = at(models, i);
                    info(s(model, "name"), o(model, "metrics").toString(2));
                  }
                }),
        false);
  }

  private void grade() {
    frame("Structured clinical model", "Cataract grade", true, true);
    heading("Multi-data assessment");
    para(
        "Enter recorded measurements in the dataset's original units. This research result is not a"
            + " diagnosis and does not assign priority. It is not automatically attached to a"
            + " patient record.");
    String[] keys = {
      "age",
      "gender",
      "ucva_right",
      "bcva_right",
      "ucva_left",
      "bcva_left",
      "outdoor_hours",
      "sunlight_code",
      "glaucoma_code",
      "retinal_code",
      "myopia_code"
    };
    String[] labels = {
      "Age in years",
      "Gender code (dataset value)",
      "Right eye UCVA",
      "Right eye BCVA",
      "Left eye UCVA",
      "Left eye BCVA",
      "Outdoor activity hours per day",
      "Sunlight protection code (dataset value)",
      "Glaucoma (1 No, 2 Yes)",
      "Retinal disease (1 No, 2 Yes)",
      "High myopia (1 No, 2 Yes)"
    };
    List<EditText> fields = new ArrayList<>();
    for (String title : labels) {
      EditText field = input(content, title, "", false);
      field.setInputType(
          InputType.TYPE_CLASS_NUMBER
              | InputType.TYPE_NUMBER_FLAG_DECIMAL
              | InputType.TYPE_NUMBER_FLAG_SIGNED);
      fields.add(field);
    }
    button(
        content,
        "Run research grade model",
        () -> {
          Map<String, String> values = new LinkedHashMap<>();
          for (int i = 0; i < keys.length; i++) {
            String value = text(fields.get(i));
            try {
              double parsed = Double.parseDouble(value);
              if (!Double.isFinite(parsed)) throw new NumberFormatException();
            } catch (Exception e) {
              error("Enter a recorded numeric value for " + labels[i] + ".");
              return;
            }
            values.put(keys[i], value);
          }
          run(
              "Running the multi-data checkpoint…",
              () -> api.post("/api/mobile/grade", values),
              r -> {
                frame("Research output", "Grade result", true, true);
                heading("For your review");
                LinearLayout c = card(content);
                renderAnalysis(c, o(r, "analysis"));
                para(
                    "Held-out accuracy: 53.69%. This dataset model is not validated for clinical"
                        + " diagnosis or treatment decisions.");
                button(content, "Back to grade inputs", () -> grade(), false);
              });
        },
        true);
  }

  private void report() {
    frame(currentCase, "Export PDF", true, true);
    heading("A complete review record");
    para(
        "Includes recorded symptoms and notes, current-round eye findings, research predictions and"
            + " four-agent trace, the doctor's review and confirmed surgery details. Export only to"
            + " a location you trust.");
    button(
        content,
        "Save report as PDF",
        () -> {
          try {
            pdfBytes = ReportPdf.create(patientData, s(me, "name"));
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT);
            intent.setType("application/pdf");
            intent.addCategory(Intent.CATEGORY_OPENABLE);
            intent.putExtra(Intent.EXTRA_TITLE, "CataTriage-" + currentCase + ".pdf");
            startActivityForResult(intent, 43);
          } catch (Exception e) {
            error("The PDF could not be created. Please try again.");
          }
        },
        true);
  }

  private void goBack() {
    if (!currentCase.isEmpty()) {
      String id = currentCase;
      if ("Overview".equals(caseTab)) {
        currentCase = "";
        refresh("Patients");
      } else loadCase(id, "Overview");
    } else renderTab();
  }

  @Override
  public void onBackPressed() {
    if (busy != null && busy.isShown()) {
      success("Please wait for the current request to complete.");
      return;
    }
    if (s(me, "username").isEmpty()) {
      super.onBackPressed();
      return;
    }
    goBack();
  }
}
