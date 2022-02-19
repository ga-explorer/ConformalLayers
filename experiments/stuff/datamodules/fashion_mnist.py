from .core import ClassificationDataModule
from typing import Any, List
import os
import torchvision


class FashionMNIST(ClassificationDataModule):

    def __init__(self, *, datasets_root: str, **kwargs: Any) -> None:
        transform = torchvision.transforms.Compose([
            torchvision.transforms.Pad(2),
            torchvision.transforms.ToTensor(),
            torchvision.transforms.Normalize(mean=(0.5,), std=(0.5,)),
            torchvision.transforms.Lambda(lambda x: x.repeat(3, 1, 1)),
        ])
        super(FashionMNIST, self).__init__(
            fit_dataset=torchvision.datasets.FashionMNIST(os.path.join(datasets_root, 'Fashion-MNIST'), train=True, download=True, transform=transform),
            test_dataset=torchvision.datasets.FashionMNIST(os.path.join(datasets_root, 'Fashion-MNIST'), train=False, download=True, transform=transform),
            **kwargs
        )

    @classmethod
    def test_dataset_name(cls) -> List[str]:
        return ['clean']
