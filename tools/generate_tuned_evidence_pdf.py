"""Three-page measured GPU tuning evidence, preserving the app's public PDF link."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Paragraph,SimpleDocTemplate,Table,TableStyle,Image,PageBreak,Spacer
from tools.generate_real_models_agents_pdf import styles,footer,navy,teal,ink,muted

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/pdf/real_models_and_agents_evidence.pdf'


def text(value,style='Bodyx'):return Paragraph(value,styles[style])


def table(rows,widths):
    result=Table([[text(str(v),'Smallx') for v in row] for row in rows],colWidths=widths)
    result.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E5F2EE')),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#CCDDDA')),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
    return result


def split_table(m):
    rows=[['Accuracy','Training','Validation','Historical test']]
    for label,metrics in [('Previous',m['baseline_metrics']),('Tuned',m['metrics'])]:rows.append([label]+[f"{metrics[k]['accuracy']:.1%}" for k in ('train','validation','test')])
    return table(rows,[42*mm,44*mm,44*mm,48*mm])


def main():
    a=json.loads((ROOT/'models/cataract_grade_multidata_real/metrics.json').read_text(encoding='utf-8'))
    b=json.loads((ROOT/'models/clinical_fusion_catscreen_real/metrics.json').read_text(encoding='utf-8'))
    doc=SimpleDocTemplate(str(OUT),pagesize=A4,leftMargin=16*mm,rightMargin=16*mm,topMargin=15*mm,bottomMargin=17*mm,title='CataTriage-AI GPU tuning and four-agent evidence - 30 October 2026')
    story=[]
    for key,m,description in [
        ('cataract_grade_multidata_real',a,'1,986 de-identified Taizhou Eye Study participants; 1,390 training, 298 validation and 298 test. The target is the maximum recorded bilateral cataract grade, grouped as 0, 1, 2 or 3+. This is a derived research target.'),
        ('clinical_fusion_catscreen_real',b,'200 real CatScreen slit-lamp images: 140 training, 20 validation and 40 test images. Participant IDs and exact image hashes were checked across splits. Labels are normal, cataract and other ocular condition.')]:
        is_grade=key.startswith('cataract_grade');folder=ROOT/'models'/key
        story += [text('GPU TUNING RESULTS | 30 OCTOBER 2026','Kicker'),text('01 - Multi-data grading' if is_grade else '02 - Image-context fusion','Title2'),text(description,'Deck'),text(m['architecture']),split_table(m),Spacer(1,6),Image(str(folder/'training_curves.png'),width=178*mm,height=68*mm)]
        ci=m['test_accuracy_bootstrap_95ci'];cm=m['test_confusion_matrix'];correct=sum(cm[i][i] for i in range(len(cm)));total=m['sample_counts']['test']
        details=f"<b>{correct} of {total} test examples correct.</b><br/>Macro-F1: {m['metrics']['test']['macro_f1']:.1%}. This weighs each class equally.<br/>Approximate 95% accuracy interval: {ci[0]:.1%} to {ci[1]:.1%}.<br/><br/>"
        if is_grade:details+='The tuned model gained 7 correct test predictions. It still missed the exact grade in 131 of 298 cases. Direct cataract diagnoses, grading fields and cataract surgery/history were excluded from the inputs. Imputation was fit on training records only.'
        else:details+='Normal: 2 of 8 found.<br/>Cataract: 15 of 27 found.<br/>Other: 5 of 5 found.<br/><br/>The tuned model gained one correct test image. Normal recognition remains weak. The interval uses participant-level bootstrap sampling.'
        panel=Table([[Image(str(folder/'test_confusion_matrix.png'),width=83*mm,height=68*mm),text(details)]],colWidths=[90*mm,88*mm]);panel.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))
        story += [panel,Spacer(1,4)]
        if is_grade:story += [text('How it was selected: six GPU CatBoost configurations, three training-only folds and fixed validation results. Five neural/tree blend weights were compared using validation only. Final selection was sealed before test predictions. The larger training score is not evidence of clinical safety.','Smallx')]
        else:story += [text('The structured branch contains eye side, reflection, image quality and illumination. The public sample does not contain the full patient clinical history, so this is not complete clinical-fusion validation. Previous training accuracy used random augmentation; the new deterministic training score is not directly comparable.','Smallx')]
        story += [PageBreak()]
    story += [text('FOUR AGENTS | ONE REVIEWABLE WORKFLOW','Kicker'),text('What happens to an input?','Title2'),text('The agents are auditable software stages. They do not act as independent doctors or approve treatment.','Deck')]
    rows=[['Stage','In easy words'],['1. Preprocessing','Check required fields, file integrity, image dimensions, lighting and declared eye side. Missing data and weak image quality are flagged.'],['2. Model inference','Run the matching research model and return class scores. The tuned grading model combines trees and a neural network; the image model combines two CNNs and acquisition context.'],['3. Safety validation','Flag uncertainty, unsupported inputs and known performance gaps. Model confidence is not disease severity or a safe waiting time. A doctor remains responsible for review.'],['4. Explanation & reporting','Present findings, scope and limitations clearly, preserve the audit record, and support doctor review. The separate workspace chatbot provides navigation and system help.']]
    story += [table(rows,[38*mm,140*mm]),Spacer(1,7),text('Why 99% training accuracy was rejected','H2x'),Image(str(ROOT/'models/clinical_fusion_catscreen_real/tuning_history.png'),width=178*mm,height=65*mm),text('The trial memorised training examples while validation performance declined. It was not used as the final model. Pretrained MobileNetV3-Small, EfficientNet-B0 and ResNet-18 were compared with participant-group folds. The selected blend uses the frozen ResNet-18 component.','Smallx'),text('How to read these results','H2x'),text('Both test sets are the same historical holdouts used previously. No candidate or epoch selection used their new test predictions. The gains are small, the uncertainty intervals overlap the previous scores, and statistical superiority is not established. No external, prospective, subgroup safety or clinical validation has been completed. More verified labelled slit-lamp images are needed for a reliable larger improvement.','Bodyx'),text('Sources: Dryad DOI 10.5061/dryad.gt410 (CC0); CatScreen official public sample: https://www.iab-rubric.org/resources/healthcare-datasets/catscreen ; PyTorch transfer-learning guidance: https://docs.pytorch.org/tutorials/beginner/transfer_learning_tutorial.html ; CatBoost GPU documentation: https://catboost.ai/docs/en/features/training-on-gpu .','Smallx')]
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    from pypdf import PdfReader
    pages=len(PdfReader(OUT).pages);assert pages==3,pages
    print(f'Updated {OUT}; {pages} pages; actual measured results only.')


if __name__=='__main__':main()
