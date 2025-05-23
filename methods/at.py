# methods/at.py

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

############################################
# AT loss function
############################################
def single_layer_at_loss(f_s, f_t, p=2):
    """
    f_s, f_t: [N, C, H, W]
    => (abs().pow(p).mean(dim=1)) -> flatten -> normalize -> MSE
    """
    if f_s.shape[2:] != f_t.shape[2:]:
        # 크기 불일치 시 adaptive pooling
        f_s = F.adaptive_avg_pool2d(f_s, (f_t.shape[2], f_t.shape[3]))

    # (1) channel-wise pow(p).mean => [N,H,W]
    sA = f_s.abs().pow(p).mean(dim=1)
    tA = f_t.abs().pow(p).mean(dim=1)

    # (2) flatten -> normalize
    sA = F.normalize(sA.view(sA.size(0), -1), dim=1)
    tA = F.normalize(tA.view(tA.size(0), -1), dim=1)

    return F.mse_loss(sA, tA)


def at_loss_dict(teacher_dict, student_dict, layer_key="feat_4d_layer3", p=2):
    """
    teacher_dict["feat_4d_layer3"], student_dict["feat_4d_layer3"] 사용
    => single_layer_at_loss 계산
    """
    f_t = teacher_dict[layer_key]  # 4D
    f_s = student_dict[layer_key]  # 4D
    return single_layer_at_loss(f_s, f_t, p=p)


############################################
# Distiller class
############################################
class ATDistiller(nn.Module):
    """
    Example of AT Distiller using the dict-based teacher/student outputs.
    1) teacher(x)->(t_dict, t_logits)
    2) student(x)->(s_dict, s_logits)
    3) at_loss_dict(...) => single_layer_at_loss
    4) total_loss = CE + alpha*AT
    """
    def __init__(self, teacher_model, student_model, alpha=1.0, p=2, layer_key="feat_4d_layer3"):
        super().__init__()
        self.teacher = teacher_model
        self.student = student_model
        self.alpha = alpha
        self.p = p
        self.layer_key = layer_key
        self.criterion_ce = nn.CrossEntropyLoss()

    def forward(self, x, y):
        # 1) teacher
        with torch.no_grad():
            t_dict, t_logit, _ = self.teacher(x)
        # 2) student
        s_dict, s_logit, _ = self.student(x)

        # 3) at_loss
        loss_at = at_loss_dict(t_dict, s_dict, layer_key=self.layer_key, p=self.p)
        # 4) CE
        loss_ce = self.criterion_ce(s_logit, y)
        total_loss = loss_ce + self.alpha * loss_at

        return total_loss, s_logit

    def train_distillation(
        self,
        train_loader,
        test_loader=None,
        lr=1e-3,
        weight_decay=1e-4,
        epochs=10,
        device="cuda"
    ):
        self.to(device)
        # student만 업데이트
        optimizer = optim.SGD(
            self.student.parameters(),
            lr=lr,
            momentum=0.9,
            weight_decay=weight_decay
        )

        best_acc = 0.0
        best_state = None

        for epoch in range(1, epochs+1):
            self.train()
            total_loss, total_num = 0.0, 0
            for x, y in train_loader:
                x, y = x.to(device), y.to(device)
                loss, _ = self.forward(x, y)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                total_loss += loss.item()*x.size(0)
                total_num  += x.size(0)

            avg_loss = total_loss / total_num

            # evaluate
            if test_loader is not None:
                acc = self.evaluate(test_loader, device)
                print(f"[Epoch {epoch}] AT => loss={avg_loss:.4f}, testAcc={acc:.2f}")
                if acc > best_acc:
                    best_acc = acc
                    best_state = {"student": self.student.state_dict()}
            else:
                print(f"[Epoch {epoch}] AT => loss={avg_loss:.4f}")

        if best_state is not None:
            self.student.load_state_dict(best_state["student"])
        return best_acc

    @torch.no_grad()
    def evaluate(self, loader, device="cuda"):
        self.eval()
        self.to(device)
        correct, total = 0, 0
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            _, s_logit = self.student(x)
            pred = s_logit.argmax(dim=1)
            correct += (pred==y).sum().item()
            total   += y.size(0)
        return 100.0 * correct / total
