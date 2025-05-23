# models/teachers/teacher_resnet.py

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision.models import resnet101, ResNet101_Weights

class TeacherResNetWrapper(nn.Module):
    """
    Teacher 모델(ResNet101) forward:
     => (feature_dict, logit, ce_loss) 형태로 반환
    feature_dict 예시:
      {
        "feat_4d": [N, 2048, H, W],   # layer4까지의 4D 출력
        "feat_2d": [N, 2048],        # global pooled
      }
    """
    def __init__(self, backbone: nn.Module):
        super().__init__()
        self.backbone = backbone
        self.criterion_ce = nn.CrossEntropyLoss()

    def forward(self, x, y=None):
        # 1) stem
        x = self.backbone.conv1(x)
        x = self.backbone.bn1(x)
        x = self.backbone.relu(x)
        x = self.backbone.maxpool(x)

        # 2) layers
        x = self.backbone.layer1(x)
        x = self.backbone.layer2(x)
        x = self.backbone.layer3(x)
        f4d = self.backbone.layer4(x)  # [N, 2048, H, W]

        # 3) global pool => 2D
        gp = self.backbone.avgpool(f4d)  # [N, 2048, 1, 1]
        feat_2d = torch.flatten(gp, 1)   # [N, 2048]

        # 4) fc => logit
        logit = self.backbone.fc(feat_2d)

        # (optional) CE loss
        ce_loss = None
        if y is not None:
            ce_loss = self.criterion_ce(logit, y)

        # Dict
        feature_dict = {
            "feat_4d": f4d,      # [N, 2048, H, W]
            "feat_2d": feat_2d,  # [N, 2048]
        }
        return feature_dict, logit, ce_loss

def create_resnet101(num_classes=100, pretrained=True):
    """
    ResNet101 로드 후, 마지막 FC 교체 => TeacherResNetWrapper
    """
    if pretrained:
        model = resnet101(weights=ResNet101_Weights.IMAGENET1K_V2)
    else:
        model = resnet101(weights=None)

    in_feats = model.fc.in_features
    model.fc = nn.Linear(in_feats, num_classes)

    teacher_model = TeacherResNetWrapper(model)
    return teacher_model
